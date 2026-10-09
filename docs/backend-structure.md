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
    mds/                       Current Medicare PDPM residents, neutral against actual rate
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
| `GET /census/live` | Per-facility census, skilled census, payer mix and summed daily rates; `payer_types` narrows census and its averages, not the payer mix, rates or empty beds; with last month's average daily census, and census and skilled census days over the look-back cards' periods -- last month, the last 6 months and the last year ending yesterday, and all time -- whole months from `monthly_payer_census_facts`, edge days from the daily facts (measured equal). ~140-280 ms |
| `GET /mds/current-medicare` | Per-facility PDPM residents on the latest census-log day -- Original Medicare, and Medicare Advantage on a PDPM contract (`facility_payer_rates.payment_method`) -- split Federal Medicare / Managed Medicare PDPM, with summed actual and case-mix-neutral daily rates and days since admission. Neutral rate is a $720 national per diem times the PDPM day factor, with no care level or facility case-mix index. ~80 ms |
| `GET /mds/pdpm-worksheet` + `/filter-options` | Every Medicare PDPM stay (Federal Medicare or Managed Medicare PDPM on a PDPM contract) whose start -- or, with `date_basis=ard`, whose 5-day assessment's ARD -- falls between `start_date` and `end_date`, discharged or not, with Active (this Medicare stay still running on the latest census day; a resident can stay in the building on another payer after it ends) and, once ended, why (`end_reason`: Discharge or Payer change) and its last day, how the stay began (`start_reason`: Admission, or Disenrollment from Medicare Advantage), stay start, ARD, MDS due date (ARD + 14, or Complete once coded) and every worksheet cell, built from the entry log: the latest set value per cell, the NTA diagnoses added and not removed with their points and band, and an entry count per cell. SQL ~100 ms for 30 days (5,743 stays) via the start-date index |
| `GET /mds/historical-medicare` | Historical Medicare PDPM's Overview tab. Per-facility Medicare PDPM stays -- the worksheet's stays, by stay start or, with `date_basis=ard`, by 5-day ARD between `start_date` and `end_date` -- split Federal Medicare / Managed Medicare PDPM, with summed Medicare days, actual revenue and case-mix-neutral revenue (national per diem times each PDPM step's day factor). A stay counts whole, through its end or the latest census day. Also `census_days`: the same selected stays' days in a bed inside the range, from their rate steps -- the daily trend's census summed, so the date basis changes them like everything else -- with `census_range_days`, the range's days with census logs. Sums only: the page divides days by stays for length of stay, revenue by days for rates, and census days by `census_range_days` for average daily census. ~120 ms for 30 days, ~490 ms for a year |
| `GET /mds/historical-medicare/residents` + `/filter-options` + `/export` | Every Medicare PDPM stay the Overview counts -- by stay start or, with `date_basis=ard`, by 5-day ARD -- with resident, payer group and plan, Medicare start, ARD, Active, Medicare days (from the payer period, equal to its step days), PDPM score (Missing care code until coded by the census day), average and neutral rate per day, total and neutral revenue. Revenue is summed from the stay's steps only for the page's 50 stays, unless the sort is a rate or revenue column, which prices every stay first. Filter options read no revenue. Page ~165 ms for 30 days, ~360 ms for a year; a year sorted by revenue ~900 ms |
| `GET /mds/historical-medicare/daily` | Each day's PDPM census, summed neutral and actual rates and summed days since admission (`stay_days`, length of stay as Current Medicare PDPM counts it; the census day matches it exactly) over the range, through the latest census day, for the stays the Overview counts -- same date range and `date_basis` -- and repeated `facility_ids` (the drilldown's) or all. Built from rate steps as a running sum of the day each starts and ends, not one row per resident-day; the selected stays are found first and only their steps read by key (scanning every step in the range and keeping theirs took 4.9-8.7 s for a year). Daily census sums to the Overview's census days exactly. ~60-100 ms for 30 days, ~500 ms for a year |
| `GET /mds/historical-medicare/categories` | The same stays counted by PDPM category per facility, in the shape of `/mds/current-medicare/categories` and by the same code (`categories.by_facility`): a stay counts once its 5-day assessment is coded by the latest census day, and in `no_score` before. ~85 ms for 30 days, ~370 ms for a year |
| `GET /mds/monthly-medicare` | Monthly Medicare PDPM Trending. Per-facility PDPM resident-days and summed actual and neutral rates for each month from `start_month` to `end_month` (YYYY-MM, at most 120), from `monthly_pdpm_census_facts`, with each month's days with census logs. Sums only: the page divides once at any scope for average daily census and rates, and takes the highest and lowest month there. ~50 ms for 24 months |
| `GET /mds/current-medicaid` | Per Texas facility: Medicaid residents on the census day (from `census_logs`), summed daily rates and days since admission, residents not yet coded and their days, and the coded residents by nursing function score band, nursing category and NTA band. The code is the latest `medicaid_assessments` row coded by the census day. Texas only: its Medicaid pays on the PDPM nursing and NTA components; Florida and Pennsylvania use other systems. No neutral rate. ~90 ms |
| `GET /mds/current-medicaid/lookback` | Texas Medicaid resident-days and summed rates today and over last month, the last 6 months, the last year and all time, from the census rows (Medicaid has no rate steps). ~190 ms |
| `GET /mds/current-medicaid/residents` + `/filter-options` + `/export` | Every Texas Medicaid resident on the census day: plan, admission, length of stay, ARD, two-letter case-mix code (Missing care code until coded), daily rate and revenue on this payer to date. A `medicaid-category` filter ("Nursing: 0-5", "Nursing Category: ...", "NTA: 0") is how a chart segment opens its residents. Page ~140 ms, filter options ~60 ms |
| `GET /mds/historical-medicaid` | Per Texas facility: the Medicaid stays whose start, or first assessment's ARD (`date_basis`), falls in the range, counted whole, with Medicaid days and revenue through the census day (each census segment's rate times its days), plus those same stays' days in a bed inside the range (the trend's census summed; the date basis changes them too) and the range's days with census logs. Selects the range's payer periods from the date column first: joined to Texas first, PostgreSQL takes Texas for one row and walks every Texas stay. ~150 ms for 30 days, ~400 ms for a year |
| `GET /mds/historical-medicaid/daily` | The census of the stays the Overview counts (same range and `date_basis`), summed daily rates and days since admission each day of the range, over `facility_ids` or every Texas facility, for the trend charts. ~40 ms for 30 days |
| `GET /mds/historical-medicaid/categories` | The same stays by their first code's nursing function score, nursing category and NTA band, once coded by the census day; not yet coded in `no_score`. ~50 ms for 30 days, ~280 ms for a year |
| `GET /mds/historical-medicaid/residents` + `/filter-options` + `/export` | Every stay the Overview counts: plan, Medicaid start, ARD, active, Medicaid days, first code, average rate and revenue. Only a revenue sort prices every stay; otherwise the page is cut first and only its 50 stays priced. Page ~50 ms for 30 days, ~300 ms for a year (~570 ms sorted by revenue) |
| `GET /mds/monthly-medicaid` | Monthly Medicaid Trending. Per Texas facility, Medicaid resident-days and summed rates for each month of the range, from `monthly_medicaid_census_facts`, with each month's days. 409 if the rollup is behind the census day. ~25 ms for 24 months or every month |
| `GET /clinical/hospital-transfers` | Hospital Transfers. Per facility, from `transfer_logs`, the transfers between `start_date` and `end_date`: the count, those within 30 days of admission, days from admission to transfer summed, rehospitalizations (admitted from a hospital and sent back within 30 days), resident days (closing census summed) for the rate per 1,000, the same count over the same number of days just before the range (`prior_transfers`, null when those days were never generated), and the counts by payer type and by clinical reason for the page's breakdowns. Repeated `payer_types` and `reasons` filter it: each breakdown applies the other filter but not its own, so it keeps every slice to click, as the Admissions payer donut does; payer types narrow resident days too. 409 unless `transfer_logs` and the net change summary have every day. ~50 ms for 30 days, ~180 ms for a year |
| `GET /clinical/hospital-transfers/daily` | Each day's hospital transfers, zero days included, with the same `payer_types` and `reasons` filters, over repeated `facility_ids` (the drilldown's) or all, for the daily trend; sums to the table's transfers exactly. ~10 ms for 30 days or a year |
| `GET /clinical/hospital-transfers/logs` + `/filter-options` + `/export` | Hospital Transfers' Logs tab: one row per transfer in the range from `transfer_logs` -- resident, facility, admission and transfer dates, length of stay, the hospital transferred to, within 30 days, admitted from, rehospitalization, payer and reason -- with server-side sort, column filters, search and a streamed CSV, built as the Discharges logs are. Page ~60-150 ms, a filter menu ~70-140 ms, a year's CSV (3.8 MB) ~0.5 s |
| `GET /clinical/incidents` | Incidents. Per facility, from `incident_logs`, the incidents between `start_date` and `end_date`, those that resulted in a hospitalization (each a hospital transfer for a fall or injury, so the count agrees with Hospital Transfers), those still open on the latest simulated day (`as_of`), resident days (closing census summed) for the rate per 1,000, the counts by time of day (morning 6-11, afternoon 12-17, evening 18-21, night 22-5), and the counts by incident type and by severity (1-5; 4 and 5 are major) for the page's breakdowns. Repeated `payer_types`, `incident_types` and `severities` filter it: each breakdown applies the other filters but not its own; payer types narrow resident days too. 409 unless `incident_logs` and the net change summary have every day. ~45 ms for 30 days, ~120 ms for a year |
| `GET /clinical/incidents/daily` | Each day's incidents, zero days included, with the same `payer_types`, `incident_types` and `severities` filters, over repeated `facility_ids` (the drilldown's) or all, for the daily trend; sums to the table's incidents exactly. ~5 ms for 30 days or a year |
| `GET /clinical/incidents/logs` + `/filter-options` + `/export` | Incidents' Logs tab: one row per incident in the range from `incident_logs` -- resident, facility, date, hour and time of day, type, severity (by name; sorted and listed in level order), resulted in hospitalization, still open on the latest simulated day, closed date and payer -- with server-side sort, column filters, search and a streamed CSV, built as the transfer logs are. Page ~60-160 ms, a filter menu ~40-60 ms |
| `GET /clinical/fever-infections` | Fever / Infections, an outbreak alert board as of `date` (default the latest day `infection_logs` has). From `infection_logs`, per facility and contagious type (respiratory, influenza-like illness, gastrointestinal), the new cases in the 72 hours and 7 days ending on the day: **Outbreak** at 3+ in 72 hours or 5+ in 7 days, **Watch** at 2 in 72 hours or 3-4 in 7 days. Each alert carries cases with fever, active cases, first and latest onset and the wings affected; totals give facilities in outbreak, on watch (without an outbreak), new cases in 72 hours and active cases, all types. 409 unless the 7 days are generated. ~20 ms |
| `GET /clinical/weight-surveillance` + `/filter-options` + `/export` | Weight Surveillance: everyone in a bed on `end_date` (default the latest day `weight_logs` has), paged, sorted and filtered server-side. From each stay's latest `weight_logs` row in the 30 days to the day: admission, current, highest and lowest weights, change since admission (lb and %), highest to lowest (lb and % of highest), the 30- and 180-day changes, and the MDS flag -- **Significant loss** at -5% in 30 days or -10% in 180, **Significant gain** likewise. The page carries the filtered list's loss and gain counts for the cards. Location menus use a list without weights; the Flag menu builds the full one. ~0.25 s a page |
| `GET /clinical/flagged-notes` + `/filter-options` + `/export` | Flagged Progress Notes: every `progress_notes` row with a watch word, newest first, with its full text for the page's note modal. Filters on facility, location, note type, payer, clinician and flag terms (any of the chosen); search covers the text too. ~0.15-0.25 s a page |
| `GET /mds/pdpm-calculator/facilities` | Every facility with its Original Medicare PDPM contract rate, the base the calculator prices a code against |
| `GET /mds/pdpm-calculator?facility_id=&code=` | The PDPM Calculator: a four-letter code (a five-character HIPPS code is accepted, its indicator ignored) priced at one facility over a full 100-day stay by `shared/pdpm.py` -- each component's share of the contract rate, CMI and 100-day total, every day's rate, the runs of days at one rate (NTA premium, baseline, each taper week), the total, average, day 1 and day 100 rates and the NTA premium. Its total equals `pdpm.stay()` to the cent. No database work beyond the facility's rate, ~4 ms |
| `GET /mds/pdpm-worksheet/catalog` | The worksheet's cells -- PT/OT primary diagnosis and GG, five SLP parts, nursing category and GG, NTA, projected HIPPS; final HIPPS is not entered but filled on each row from the coded assessment (PDPM code + 1), and both HIPPS codes come priced over a 100-day stay (average, neutral and total revenue, `final_rates` / `projected_rates`) by `shared/pdpm.py`, the formula the data is generated with -- with what each accepts, and the CMS NTA comorbidity list with points |
| `GET /mds/pdpm-worksheet/{payer_stay_id}/entries?field=` | One cell's whole log, entries and replies, oldest first |
| `POST /mds/pdpm-worksheet/{payer_stay_id}/entries` | **Writes.** Appends one entry -- set a value, add or remove an NTA diagnosis, or reply to an entry -- validated against the catalogue, with the signed-in username. The only report route on `DbWriteConnection` |
| `GET /mds/medicaid-worksheet` + `/filter-options` + `/catalog` | The Medicaid PDPM Worksheet: every Texas Medicaid stay whose start, or first assessment's ARD, falls in the range, with Active, how it began and ended, ARD, MDS due (ARD + 14, or Complete once coded), the final two-letter code once coded, and its cells built from the same entry log. Its cells are the Medicare worksheet's nursing and NTA ones plus a projected two-letter code (`projected_code`); no code is priced, since a Texas Medicaid rate is the census day's rate. Page ~90-130 ms for 30 days, ~350 ms for a year |
| `GET` + `POST /mds/medicaid-worksheet/{payer_stay_id}/entries` | One cell's log, and **writes** one entry to `pdpm_worksheet_entries`, the Medicare worksheet's append-only log, validated against the Medicaid catalogue; only a Texas Medicaid payer period takes one. On `DbWriteConnection` |
| `GET /mds/current-medicare/lookback` | Per-facility PDPM resident-days and summed actual and neutral daily rates for today and four average periods, as Daily Census defines them: last month (the previous calendar month), the last 6 months and the last year (ending yesterday), and all time (first generated day to yesterday), each with its generated days. The page divides once: average daily census is resident-days over days, rates are summed rates over resident-days. Whole months come from `monthly_pdpm_census_facts`; only today and the days of a rollup month outside a period come from the rate steps, about 13 days of them. Today matches `/mds/current-medicare` exactly and every average matched the all-steps query to the cent. ~220 ms, from 1.1 s reading every step; 409 when the rollup is behind the census logs |
| `GET /mds/current-medicare/categories` | Per-facility PDPM residents counted by PDPM category; primary diagnosis is the PT/OT clinical category, the first letter of the code, `pt_ot` is the function score band (0-5, 6-9, 10-23, 24) of the same letter, `slp` is the SLP group, the second letter, as `speech_N_swallowing_M` (0-3 speech conditions by 0-2 swallowing needs), `nursing` is the nursing function score band (0-5, 6-14, 15-16) from the score on `pdpm_assessments`, `nursing_category` the nursing clinical category (Extensive Services ... Reduced Physical Function) from the nursing letter, by `shared/pdpm.NURSING_CATEGORIES`, `nta` is the NTA comorbidity points band (0, 1-2, 3-5, 6-8, 9-11, 12+), the fourth letter, `depression` is yes / no from the flag on `pdpm_assessments`, and `speech` counts residents with each SLP condition (cognitive impairment, acute neuro, mechanically altered diet, swallowing disorder, SLP comorbidity) from flags on `pdpm_assessments`; those overlap and do not sum to the residents. A resident counts in a category only from the assessment's `coded_date`; before it they are in `no_score`. ~80 ms |
| `GET /mds/current-medicare/residents` + `/filter-options` + `/export` | Every PDPM resident on the census day: payer group, plan name, length of stay, admission date, ARD (the 5-day assessment reference date, day 1-8 of the Medicare stay), PDPM score (four-letter PDPM code from `pdpm_assessments`; ARD blank and score Missing care code before its `coded_date`, 2-4 days after the ARD), average rate and PDPM revenue on this payer to date. A `pdpm-category` filter ("PT/OT: 0-5", "Nursing: 6-14", "Speech Comorbidity: MAD" ...) matches one part of one Overview category, which is how a click on an Overview chart segment opens its residents; its options list only parts with residents under the other filters. Page ~100-150 ms, filter options ~30 ms |

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
