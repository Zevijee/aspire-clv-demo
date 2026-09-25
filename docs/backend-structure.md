# Backend structure

A read-only FastAPI reporting API over the shared schema. It never creates tables
and never generates data: migrations and generation are separate commands in
`sandbox-data`. Starting the API against an unmigrated database fails on purpose.

## Run it

From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
python backend/manage.py serve --reload
```

Binds `127.0.0.1:8000`. Documentation at `/docs`, OpenAPI at `/openapi.json`.
`--host 0.0.0.0` for containers. `--reload` watches `backend/` and `shared/` while
excluding staged schema drafts.

## Layout

```text
backend/
  manage.py                    Local server command
  requirements.txt
  app/
    main.py                    Lifespan, CORS, error handlers, router registration
    config.py                  Settings from the root .env and the environment
    database.py                Pool, readiness, per-request read transactions
    common/
      dates.py                 Inclusive date ranges and report-local today
      locations.py             Resolve saved facility IDs from location selections
      tables.py                Bounded pagination and allowed sort columns
      errors.py                Safe, expected API errors
    reference/                 Shared location and payer catalogues
    adt/admissions/            Overview, logs, filter options, CSV export
    adt/referring_hospital/    Referral performance per hospital, fixed 36-month window
    census/                    Live census against last month's daily average
    system/                    Health, readiness, generator coverage
```

One package per feature, each with `routes.py`, `service.py` and `schemas.py`.
Admissions adds `logs.py` for shared event predicates.

- **Routes** handle HTTP parameters, dependencies and response contracts.
- **Services** own queries and domain calculations. They take a connection and
  explicit selections, and never call another endpoint over HTTP.
- **Schemas** define API shapes, not a second copy of the database schema.
- **`common/`** holds shared mechanics. Business calculations stay with the feature
  that owns them and may be imported by other services.

There is no generic report engine and no empty routers for future modules. A module
is not required to expose the same layouts, date limits, filters or endpoints as any
other. That was the right call at one report; see
[roadmap.md](roadmap.md#factoring-out-the-shared-report-shape) for when it stops
being right.

## Endpoints

All under `/api/v1`.

| Endpoint | Behaviour |
| --- | --- |
| `GET /health` | Process liveness after startup, no database query |
| `POST /auth/login` | Checks the password; sets the access cookie and a new refresh token |
| `POST /auth/refresh` | Renews the access cookie and rotates the refresh token; 401 means sign in again |
| `POST /auth/logout` | Revokes the refresh token's whole sign-in and clears both cookies |
| `GET /auth/session` | Who the access cookie belongs to, or null |
| `GET /ready` | Connectivity, schema and backfill readiness; 503 when unavailable |
| `GET /data-status` | Completion dates, counts and continuity per generator |
| `GET /reference/locations` | Paginated facilities with saved IDs and full hierarchy |
| `GET /reference/payers` | Paginated payer catalogue with type and skilled flag |
| `GET /adt/admissions/overview` | One period aggregated from saved daily facts |
| `GET /adt/admissions/logs` | Paginated matching admissions with saved IDs |
| `GET /adt/admissions/logs/filter-options` | Distinct values across the filtered result |
| `GET /adt/admissions/logs/export` | The entire matching result as streamed CSV |
| `GET /adt/discharges/overview` | Totals, locations, payer/destination/disposition breakdowns |
| `GET /adt/discharges/logs` + `/filter-options` + `/export` | Discharge events |
| `GET /adt/payer-changes/overview` | Counts, residents affected, from/to transition matrix |
| `GET /adt/payer-changes/logs` + `/filter-options` + `/export` | Payer change events |
| `GET /adt/net-change/overview` | Census movement: opening, flows, closing, by payer |
| `GET /adt/net-change/monthly` | Monthly totals with their days nested |
| `GET /adt/net-change/monthly-locations` | Per-facility monthly totals |
| `GET /adt/net-change/logs` + `/filter-options` + `/export` | Admissions, discharges and payer changes as one list |
| `GET /adt/referring-hospital/performance` | Referral volume per hospital over 36 complete months |
| `GET /census/trending/daily` | Closing census each day of a range, over given `facility_ids` or all, optionally narrowed by `payer_types`. 16 ms for 30 days, 60 ms for a year |
| `GET /census/trending` | Per-facility census days, open and close census over a date range, optionally narrowed by `payer_types`. 19 ms for 30 days, 67 ms for a year |
| `GET /census/resident-summaries` + `/filter-options` + `/export` | Every resident ever admitted: days, stays, admissions, discharges, current, payers. 35-175 ms |
| `GET /census/residents` + `/filter-options` + `/export` | Everyone in a bed on the census day, from census_logs, with care level and the day's rate |
| `GET /census/live` | Per-facility census, skilled census, payer mix and summed daily rates; `payer_types` narrows census and its averages, not the payer mix, rates or empty beds; with last month's average daily census and a history lookback from yesterday to a year ago. ~200 ms |

Every overview reads a fact table and nothing else. Every logs endpoint reads source
rows, because a log lists named residents and a fact table has no resident in it.

Three rules the overviews share, each with a reason:

- **Facets omit their own filter.** The payer breakdown on Discharges keeps the
  destination filter and drops the payer one, so the chart still shows what the
  selection is being compared against.
- **Census is a level, not a flow.** Net Change reads opening from the first day of
  the range and closing from the last. Summing census across days would count every
  resident once per day present.
- **Non-additive measures are counted live, never stored.** Residents affected on
  Payer Changes is a distinct count: in one 30-day window 491 residents changed payer
  more than once, so any sum of per-day rows would over-count by 13%.

Referring Hospital is the one report that takes no date range. Its period is part of
its definition — the last 3 complete months against the preceding 24, inside 36
months of history — so the service derives the window from the report's today rather
than from the caller, and excludes the current month because a partial month would
understate every average. Location selection still narrows which admissions count.
Naming a `hospital` returns that one hospital with a month series on each receiving
facility; the list form returns all 384 with facility totals and no series, which is
what the table shows. Measured on the full dataset: 105 ms for the list, 13 ms for
one hospital.

Reference lists return `{items, total, limit, offset}` and accept `limit` (1–500,
default 50), `offset`, `sort` and `direction=asc|desc`. Allowed sorts are
`facility_name` (default), `state`, `portfolio_name`, `region_name`, `beds` for
locations; `payer_name` (default), `payer_type`, `is_skilled` for payers. Stable ID
tie-breakers keep equal sort values deterministic, counts and rows share one
snapshot, all values are bound parameters, and client column names must resolve
through a feature-owned allowlist.

`data-status` reports completion checkpoints, not a promise that a given report
exists. A gap makes `contiguous` and `complete_through_today` false; the latest date
alone does not prove coverage.

## Location selection

Repeated `states`, `portfolio_ids`, `region_ids` and `facility_ids` parameters.
Selections are **OR within one level and AND between levels**. An empty selection
means unfiltered; a non-empty selection matching nothing returns an empty result,
and never silently becomes unfiltered. `match_none=true` states an empty selection
explicitly.

Grouping is a separate choice from selection: `group_by` may be `state`,
`portfolio`, `region` or `facility` regardless of what was selected.

Selections narrow data. They are **not** an access-control boundary — sign-in
gates the whole API, and there is no per-facility authorisation.

## The admissions overview

```text
/api/v1/adt/admissions/overview?start_date=2026-09-01&end_date=2026-09-07&group_by=state
```

Dates are inclusive, maximum range 3,660 days. Also accepts repeated `payer_types`
and `source_types`. The response contains `range`, `group_by`, `totals`,
`locations`, `by_payer`, `by_source`, `hospitals`, `daily` and `data_status`.

Counts include admissions, readmissions and 30-day readmissions. Averages divide by
every calendar day in the range, not by days with data — so a facility with 12
admissions across 6 of 31 days reports 0.39/day, not 2.0. Referring hospital names
are deduplicated across dates and locations. `medicaid_pending_admissions` counts
admissions that began pending Medicaid, and survives the retroactive payer
correction.

Current and prior periods are separate calls; the frontend computes the difference.
An unavailable prior period leaves the current report usable.

### How the service aggregates

Read `backend/app/adt/admissions/service.py` alongside this.

**Join only what the grouping key needs.** Facility IDs are already on the fact
rows, so grouping by facility joins nothing. Region needs `facilities`, portfolio
needs `facilities` and `regions`, state needs all three. Payer-type filters resolve
through a subquery rather than a join for the same reason. Joining the full
hierarchy plus `payers` on every query cost 124 ms where the bare aggregate cost 14.

**One scan, several groupings.** Totals, the daily trend and the location rows come
from a single query using `GROUPING SETS`, with `GROUPING()` to tell the result rows
apart. The overall and per-location hospital breakdowns share a second such scan.

**Facets omit their own filter.** The payer chart applies the source filter but not
the payer filter, so alternative payers stay visible and clickable; the source chart
is the mirror image. Everything else applies both. This is defined per response, not
applied globally.

**Distinct referring hospitals is derived, not counted.** It is the one
non-additive metric, and `COUNT(DISTINCT ...)` alongside the sums cost 183 ms of a
275 ms request — more than every other aggregate combined. Totals and location rows
take the length of the hospital breakdown they already carry. Only the daily rows,
which have no name breakdown, need their own count, and they deduplicate first and
count rows rather than using `COUNT(DISTINCT)` per group.

**Parent scopes are never stored.** Every level above facility is a `GROUP BY` over
the facility grain, so a parent can never be double-counted with its own children
and no scope-day is written twice.

### Completeness versus emptiness

These are different, and only one is an error.

| Situation | Result |
| --- | --- |
| Day generated, nothing happened | `200`, zeros |
| Day never generated | `409 summary_unavailable` |

Completeness comes from the seeder's committed checkpoints in `sandbox_daily_runs`,
not from whether fact rows exist. A completed day with no admissions has no rows and
must read as zero. The `locations` array still lists a selected facility with no
activity, and `daily` still contains every calendar date, because both are built
from the selection and the range rather than from returned rows.

Incompatible or missing data returns `409` with a readable explanation.

## Log endpoints

Accept `start_date`, `end_date`, a JSON `filters` object mapping column IDs to
string arrays, a literal `search`, and the common pagination and sort parameters.
Filters are OR within a column and AND between columns. `facility-id` preserves the
exact overview selection; `payer` accepts canonical codes or display labels;
`medicaid-pending-on-admission=Yes` filters `started_medicaid_pending`.

Filter options require `column` and ignore only that column's own selected values,
computed across the entire filtered result rather than the current page. CSV export
uses the same predicates and sort without pagination. The browser never loads all
admission records to build an overview.

## Request lifecycle

The app creates one SQLAlchemy pool per worker and disposes it on shutdown.
Database work uses synchronous route and dependency functions; startup and shutdown
database operations run in FastAPI's thread pool.

Each reporting dependency acquires the shared side of the seeder's lifecycle
advisory lock before opening a read-only repeatable-read snapshot. An upgrade in
progress returns 503 promptly rather than reading between backfill batches. The
schema head is checked per request; full migration and backfill checksum
compatibility is checked at startup and on `/ready`. Restart the API after changing
its code or schema.

Normal daily generation proceeds concurrently. A request sees committed data from
one consistent snapshot; another request may see a newer completed day. Readiness is
separate from freshness. Long-running requests can delay an upgrade while holding
the shared lock, so queries have a configurable statement timeout.

## Errors

Database exceptions return safe messages with no SQL text, bound values or
connection strings. Validation errors keep field locations and explanations without
echoing supplied values. Expected errors use `{code, detail}`; validation errors add
an `errors` list. Both shapes appear in OpenAPI.

## Configuration

Settings read the root `.env` regardless of working directory; environment variables
override it. Unrelated `.env` values are ignored.

**Every setting except `DATABASE_URL` takes an `API_` prefix.** `DATABASE_URL` is
aliased and does not. This trips people up: a bare `CORS_ORIGINS` in `.env` is
silently ignored, and the defaults apply.

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | Required; the same database as the seeder |
| `API_CORS_ORIGINS` | JSON array `["http://localhost:5173","http://127.0.0.1:5173"]` |
| `API_TIMEZONE` | `America/New_York` |
| `API_POOL_SIZE` | 5 per worker |
| `API_MAX_OVERFLOW` | 10 additional per worker |
| `API_POOL_TIMEOUT_SECONDS` | 15 |
| `API_CONNECT_TIMEOUT_SECONDS` | 10 |
| `API_STATEMENT_TIMEOUT_MS` | 30000 |
| `API_SESSION_SECRET` | Generated per process; set it on a server, or every restart signs everyone out |
| `API_SESSION_HTTPS_ONLY` | `false`; `true` behind HTTPS |
| `API_SESSION_MINUTES` | 15, the access cookie. Signed, not stored, so it cannot be revoked |
| `API_REFRESH_DAYS` | 7, the refresh token. Rotated on every use, so this is idle time |

`API_CORS_ORIGINS` is parsed as JSON, so it needs a JSON array, not a comma-separated
list. CORS currently permits GET only; add methods and an authentication policy
before adding write endpoints. Raising worker count multiplies the connection
budget — do not raise both blindly.

In Docker the browser reaches the API through the frontend's own origin via an nginx
proxy, so CORS only matters when calling a published API port directly.

## Adding a report module

End to end, using discharges as the example. The order matters: each step's output
is the next step's input.

**1. Fact table.** Add it to the staged schema, not the active one:
`python manage.py stage`, edit `shared/database/staged/schema.py`, then
`python manage.py revision --message "..."`. Grain is one row per event at its
natural dimensions, with additive measures. Keep dimension keys (`payer_id`, not
`payer_type`) — the finer grain measured as free, and it makes future breakdowns
possible without regenerating.

Review the generated migration. Autogeneration will not write CHECK constraints and
will not drop tables; both must be added by hand. See
[database-workflow.md](database-workflow.md).

**2. Generator.** A new module in `sandbox-data/summary_generators/` following
`aspire-admissions.py`: one `INSERT ... SELECT` from the source tables into a
staging table, then an atomic replacement of the selected dates. Register a
`DailyGenerator` with `bulk_dates = True` and `depends_on = ('adt',)`.

**3. Service.** A new `backend/app/adt/discharges/service.py`. Join only what the
grouping key needs, use `GROUPING SETS` for the multi-grain queries, derive
non-additive metrics from breakdowns you already have, and check completeness
against `sandbox_daily_runs` rather than row presence.

**4. Schemas and routes.** Pydantic models for the response, a router with the
feature prefix, registered in `main.py`.

**5. Frontend.** A client under `frontend/src/features/adt/api/`, then reconnect the
existing components. The discharge components already exist and already expect a
shape — read them before designing the response, and see
[roadmap.md](roadmap.md#dead-frontend-reports) for what each one calls today.

**6. Documentation.** The endpoint table above, and
[database-schema.md](database-schema.md) regenerates itself on `update`.

Averages, ratios and length of stay deserve care: sum the numerators and divide
once. Never average a column of averages, and store `sum_los` and a count as
separate additive columns rather than a pre-computed mean, or every roll-up above
facility level is silently wrong.
