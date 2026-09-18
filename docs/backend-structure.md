# Backend structure

The FastAPI foundation lives in `backend/app`. It imports database tables directly
from `shared/database/schema.py`. The existing seeder, migrations, and backfills
remain separate commands; starting the API never creates tables or generates data.

## Run locally

From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
python backend/manage.py serve --reload
```

Or from `backend`: `python manage.py serve --reload`.
The API binds to `127.0.0.1:8000`. API documentation is at
<http://127.0.0.1:8000/docs>, with OpenAPI at `/openapi.json`.

The existing root `.env` supplies `DATABASE_URL`. Startup requires a database
compatible with the current shared schema and completed required backfills.
If necessary, run `python manage.py update` from `sandbox-data` first. Database
readiness does not imply that all report dates have been generated: inspect
`/api/v1/data-status` for saved generator coverage.

The frontend uses `http://localhost:8000` by default, or `VITE_API_BASE_URL`.
Admissions Overview and its log drilldowns use the new API. Other reports still
need their own integration with the rebuilt backend.

## Current files and ownership

```text
backend/
  manage.py                    # Local server command
  requirements.txt
  app/
    main.py                    # App lifespan, CORS, errors, router registration
    config.py                  # Root .env and environment settings
    database.py                # Pool, readiness, per-request read transactions
    common/
      dates.py                 # Inclusive date ranges and report-local today
      locations.py             # Resolve saved facility IDs from location selections
      tables.py                # Bounded pagination and allowed sort columns
      errors.py                # Safe, expected API errors
    reference/
      routes.py                # Shared location and payer endpoints
      service.py               # Reference queries
      schemas.py               # Request and response shapes
    adt/admissions/
      routes.py                # Overview, logs, filter options and CSV
      service.py               # Group saved daily admission facts
      schemas.py               # Overview request/response shapes
      logs.py                  # Shared event predicates and detail queries
    system/
      routes.py                # Health, readiness and generator coverage
      service.py
      schemas.py
```

ADT referrals, movement, discharges, payer changes, census, staffing,
AR, AP and therapy get their own feature packages when implemented. There are no
empty routers for future modules and no generic report engine to configure first.

- Routes handle HTTP parameters, dependencies and response contracts.
- Services own database queries and domain calculations. They accept a connection
  and explicit selections; they do not call another local endpoint over HTTP.
- Schemas define API shapes, not a duplicate database schema.
- Shared mechanics belong in `common`; business calculations stay with their
  owning feature and can be imported by multiple services.
- A module is not required to expose identical report layouts, date limits,
  filters, calculations or endpoints to other modules.

The current API is a local, read-only demo foundation. Authentication and
facility-access authorization are not implemented. Location selection narrows
data; it is not an access-control boundary.

## Implemented endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /api/v1/health` | Process liveness after startup, without a database query |
| `GET /api/v1/ready` | Current connectivity, schema and required backfill readiness; 503 when unavailable |
| `GET /api/v1/data-status` | Completion dates/counts and continuity for each generator with saved checkpoints |
| `GET /api/v1/reference/locations` | Paginated facility records with their saved IDs and full state/portfolio/region paths |
| `GET /api/v1/reference/payers` | Paginated payer catalog, including type and skilled flag |
| `GET /api/v1/adt/admissions/overview` | One period aggregated from saved daily admission summaries |
| `GET /api/v1/adt/admissions/logs` | Paginated matching admissions with saved resident/facility/stay IDs |
| `GET /api/v1/adt/admissions/logs/filter-options` | Distinct values across the filtered result, excluding the opened column's filter |
| `GET /api/v1/adt/admissions/logs/export` | Stream the entire matching log result as CSV |

Reference lists return `{items, total, limit, offset}`. Both support `limit` (1–500,
default 50), `offset`, `sort`, and `direction=asc|desc`.

Locations accept repeated `states`, `portfolio_ids`, `region_ids`, and
`facility_ids` query parameters. For example:

```text
/api/v1/reference/locations?states=TX&states=FL&limit=100&sort=facility_name
/api/v1/reference/payers?is_skilled=true&search=Medicare&limit=100
```

Selections are OR within one level and AND between levels. Empty selections mean
unfiltered; a nonempty selection matching nothing returns an empty result. Grouping
is a separate report choice. The locations list describes facilities and their
parents; it does not list parent locations with no facilities.

Payers also accept repeated `payer_types`, optional `is_skilled`, and `search`
(literal case-insensitive payer-name search). Allowed sorts are:

- Locations: `facility_name` (default), `state`, `portfolio_name`, `region_name`, `beds`.
- Payers: `payer_name` (default), `payer_type`, `is_skilled`.

Stable ID tie-breakers keep equal sort values deterministic. Counts and rows use
the same snapshot. All query values are bound parameters; client column names
must resolve through a feature-owned allowlist.

`data-status` reports completion checkpoints, not a promise that every future
report or JSON payload exists. An absent generator has no recorded completed
days. A gap makes `contiguous` and `complete_through_today` false; the latest date
alone does not prove coverage. Each report must validate its own requested range
and required sources, and distinguish unavailable data from a real zero.

## Frontend interactions the next features must preserve

- A page and a modal use the same endpoint with independent selections.
- Current and prior periods use separate calls to the same summary endpoint.
- Location grouping and location selection are independent, using saved IDs.
- Summary counts, detail logs, filter options and exports share predicates.
- Chart breakdowns that act as filters can omit their own selected dimension
  while retaining the others, so alternative choices stay visible. Define that
  behavior explicitly per response; do not silently apply one filter set everywhere.
- Read prebuilt summaries for dashboards; fetch paginated event/resident rows on
  demand. Keep large exports separate from loading an overview.
- Table filter values come from the entire filtered result, not one page. The
  filter being opened is excluded from its own option query. Share the mechanics
  while keeping permitted columns and SQL expressions with the feature.
- Sum additive measures; deduplicate distinct hospitals/residents, weight LOS
  averages, and use correct opening/closing boundaries for census.
- Reuse movement data for net change and monthly views rather than duplicating
  ADT calculations in each screen's endpoint.

## Admissions overview contract

```text
/api/v1/adt/admissions/overview?start_date=2026-09-01&end_date=2026-09-07&group_by=state
```

Dates are inclusive. `group_by` is `state`, `portfolio`, `region`, or `facility`.
The endpoint accepts the same saved location IDs as the locations reference API,
plus repeated `payer_types` and `source_types`. `match_none=true` explicitly
represents an empty matching location selection. The maximum range is 3,660 days.

The response contains `range`, `group_by`, `totals`, `locations`, `by_payer`,
`by_source`, `hospitals`, `daily`, and `data_status`. Each location includes its
hierarchy path and selected facility IDs for drilldowns. Counts include admissions,
readmissions, and 30-day readmissions. Averages divide by every calendar day in the
range. Referring hospital names are deduplicated across dates and locations.
`medicaid_pending_admissions` counts admissions that initially required Medicaid
approval, even after their regular payer fields have been retroactively corrected.
Log rows expose `started_medicaid_pending` and `medicaid_approved_date`; the former
can be filtered with `medicaid-pending-on-admission=Yes` in the JSON filters object.

The API reads `daily_admission_facts`, which stores additive measures at
facility/payer/source grain. Every parent scope is a `GROUP BY` over that grain,
so a parent can never be combined with its own children and no scope-day is
stored more than once. Dashboard totals are never recomputed from resident/event
rows. Payer charts omit their own payer filter; source charts omit their own
source filter. All other metrics apply both filters. Current and prior periods
are separate calls; the frontend computes their difference.

Join no more of the location hierarchy than the grouping key needs; grouping by
facility joins nothing, because facility IDs are already on the fact rows. Payer
type filters resolve through a subquery rather than a join for the same reason.
Totals, daily counts and location rows come from one scan using `GROUPING SETS`,
as do the overall and per-location hospital breakdowns.

Distinct referring hospitals is the one non-additive metric. Counting it with
`COUNT(DISTINCT ...)` alongside the sums costs more than every other aggregate
combined, so totals and location rows take the length of the hospital breakdown
they already carry, and the daily rows deduplicate first and count rows.

Missing days return 409 with a readable explanation. Completeness is the seeder's
committed date checkpoints in `sandbox_daily_runs`, not the presence of rows: a
completed day with no admissions has no fact rows and reads as zero. An
unavailable prior period leaves the current report usable and comparison values
unavailable. No migration or new generation is required when existing daily
facts are complete.

Log endpoints accept `start_date`, `end_date`, JSON `filters` (column IDs mapped
to string arrays), literal `search`, and the common pagination/sort parameters.
Filters are OR within a column and AND between columns. `facility-id` preserves
the exact summary selection; `payer` accepts canonical codes or display labels.
Filter options require `column` and ignore only that column's selected values.
CSV uses the same predicates and sort, without pagination. The browser does not
load all admission records to build the overview.

## Database lifecycle and concurrency

Schema drafting is separate from active API code. `manage.py stage` in sandbox-data
creates `shared/database/staged/schema.py`; new revisions and backfills remain in
that draft directory. The API neither imports it nor discovers its migrations,
and the development launcher excludes it from reload watching. Restart an existing
launcher once to pick up those exclusions.

`manage.py update` is the activation boundary: it publishes a changed draft,
completes migrations/backfills, then catches up missing days with the new schema.
Drafting leaves the current API usable; applying changes may temporarily block
requests under the lifecycle lock. Development reload is requested on successful
application; a server without `--reload` must be restarted. Backend query changes
for renamed or removed columns are still part of the same implementation change.

The app creates one SQLAlchemy pool per worker and disposes it on shutdown.
Database work uses synchronous route/dependency functions; startup/shutdown
database operations run in FastAPI's thread pool.

Each reporting dependency acquires the shared side of the seeder's lifecycle lock
before starting a read-only, repeatable-read snapshot. An active upgrade returns
503 promptly; the API never reads between upgrade backfill batches. The database
head is checked for each request. Full migration/backfill checksum compatibility
is checked at startup and `/ready`. Restart the API after changing its code/schema.

Normal daily generation can proceed concurrently. A request sees committed data
from one consistent snapshot; another request may see a newer completed day.
Readiness is separate from freshness. Long-running requests can delay an upgrade
while holding the shared lock, so queries have a configurable statement timeout.

Database exceptions return safe messages without SQL text, bound values or
connection strings. Validation errors retain field locations and explanations
without echoing supplied values. Expected errors use `{code, detail}`; validation
errors also contain an `errors` list. Response schemas appear in OpenAPI.

## Configuration

Settings read the root `.env` regardless of the working directory; environment
variables override that file. Unrelated `.env` values are ignored.

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | Required; same database as the seeder |
| `API_CORS_ORIGINS` | JSON array `["http://localhost:5173", "http://127.0.0.1:5173"]` |
| `API_TIMEZONE` | `America/New_York` |
| `API_POOL_SIZE` | 5 connections per worker |
| `API_MAX_OVERFLOW` | 10 additional connections per worker |
| `API_POOL_TIMEOUT_SECONDS` | 15 |
| `API_CONNECT_TIMEOUT_SECONDS` | 10 |
| `API_STATEMENT_TIMEOUT_MS` | 30000 |

CORS currently permits GET requests for the implemented read APIs. Add methods
and the relevant authentication policy when adding write endpoints. Changing
worker count multiplies the connection budget; do not increase both blindly.

The app follows FastAPI's [lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [dependency cleanup](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
patterns. Database ownership and change procedures remain in
[database-workflow.md](database-workflow.md).
