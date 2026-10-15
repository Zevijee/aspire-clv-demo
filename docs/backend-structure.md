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
    staffing/                  HPPD: hours per patient day by facility and role, against target
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
| `GET /census/live` | Per-facility census, skilled census, payer mix and summed daily rates; `payer_types` narrows census and its averages, not the payer mix, rates or empty beds; with last month's average daily census, and census and skilled census days over the look-back's periods -- single days (yesterday, and the same day a week, a month, 6 months and a year back), then last month, the last 6 months and the last year ending yesterday, and all time, each flagged `average` -- whole months from `monthly_payer_census_facts`, edge days from the daily facts (measured equal). ~140-280 ms |
| `GET /mds/current-medicare` | Per-facility PDPM residents on the latest census-log day -- Original Medicare, and Medicare Advantage on a PDPM contract (`facility_payer_rates.payment_method`) -- split Federal Medicare / Managed Medicare PDPM, with summed actual and case-mix-neutral daily rates and days since admission. Neutral rate is a $720 national per diem times the PDPM day factor, with no care level or facility case-mix index. ~80 ms |
| `GET /mds/pdpm-worksheet` + `/filter-options` | Every Medicare PDPM stay (Federal Medicare or Managed Medicare PDPM on a PDPM contract) whose start -- or, with `date_basis=ard`, whose 5-day assessment's ARD -- falls between `start_date` and `end_date`, discharged or not, with Active (this Medicare stay still running on the latest census day; a resident can stay in the building on another payer after it ends) and, once ended, why (`end_reason`: Discharge or Payer change) and its last day, how the stay began (`start_reason`: Admission, or Disenrollment from Medicare Advantage), stay start, ARD, MDS due date (ARD + 14, or Complete once coded) and every worksheet cell, built from the entry log: the latest set value per cell, the NTA diagnoses added and not removed with their points and band, and an entry count per cell. SQL ~100 ms for 30 days (5,743 stays) via the start-date index |
| `GET /mds/historical-medicare` | Historical Medicare PDPM's Overview tab. Per-facility Medicare PDPM stays -- the worksheet's stays, by stay start or, with `date_basis=ard`, by 5-day ARD between `start_date` and `end_date` -- split Federal Medicare / Managed Medicare PDPM, with summed Medicare days, actual revenue and case-mix-neutral revenue (national per diem times each PDPM step's day factor). A stay counts whole, through its end or the latest census day. Also `census_days`: the same selected stays' days in a bed inside the range, from their rate steps -- the daily trend's census summed, so the date basis changes them like everything else -- with `census_range_days`, the range's days with census logs. Sums only: the page divides days by stays for length of stay, revenue by days for rates, and census days by `census_range_days` for average daily census. ~120 ms for 30 days, ~490 ms for a year |
| `GET /mds/historical-medicare/residents` + `/filter-options` + `/export` | Every Medicare PDPM stay the Overview counts -- by stay start or, with `date_basis=ard`, by 5-day ARD -- with resident, payer group and plan, Medicare start, ARD, Active, Medicare days (from the payer period, equal to its step days), PDPM score (Missing care code until coded by the census day), average and neutral rate per day, total and neutral revenue. Revenue is summed from the stay's steps only for the page's 50 stays, unless the sort is a rate or revenue column, which prices every stay first. Filter options read no revenue. Page ~165 ms for 30 days, ~360 ms for a year; a year sorted by revenue ~900 ms |
| `GET /mds/historical-medicare/daily` | Each day's PDPM census, summed neutral and actual rates and summed days since admission (`stay_days`, length of stay as Current Medicare PDPM counts it; the census day matches it exactly) over the range, through the latest census day, for the stays the Overview counts -- same date range and `date_basis` -- and repeated `facility_ids` (the drilldown's) or all. Built from rate steps as a running sum of the day each starts and ends, not one row per resident-day; the selected stays are found first and only their steps read by key (scanning every step in the range and keeping theirs took 4.9-8.7 s for a year). Daily census sums to the Overview's census days exactly. ~60-100 ms for 30 days, ~500 ms for a year |
| `GET /mds/historical-medicare/categories` | The same stays counted by PDPM category per facility, in the shape of `/mds/current-medicare/categories` and by the same code (`categories.by_facility`): a stay counts once its 5-day assessment is coded by the latest census day, and in `no_score` before. ~85 ms for 30 days, ~370 ms for a year |
| `GET /mds/monthly-medicare` | Monthly Medicare PDPM Trending. Per-facility PDPM resident-days and summed actual and neutral rates for each month from `start_month` to `end_month` (YYYY-MM, at most 120), from `monthly_pdpm_census_facts`, with each month's days with census logs. Sums only: the page divides once at any scope for average daily census and rates, and takes the highest and lowest month there. ~50 ms for 24 months |
| `GET /mds/current-medicaid` | Per Texas facility: Medicaid residents on the census day (from `census_logs`), summed daily rates and days since admission, residents not yet coded and their days, and the coded residents by nursing function score band, nursing category and NTA band. The code is the latest `medicaid_assessments` row coded by the census day. Texas only: its Medicaid pays on the PDPM nursing and NTA components; Florida and Pennsylvania use other systems. No neutral rate. ~90 ms |
| `GET /mds/current-medicaid/lookback` | Texas Medicaid resident-days and summed rates today, on the same single earlier days as Daily Census, and over last month, the last 6 months, the last year and all time, from the census rows (Medicaid has no rate steps). ~190 ms |
| `GET /mds/current-medicaid/residents` + `/filter-options` + `/export` | Every Texas Medicaid resident on the census day: plan, admission, length of stay, ARD, case-mix code, nursing letter, cognitive impairment digit and NTA letter (Missing care code until coded), daily rate and revenue on this payer to date. A `medicaid-category` filter ("Nursing: 0-5", "Nursing Category: ...", "Cognitive Impairment: Mild", "NTA: 0") is how a chart segment opens its residents. Page ~140 ms, filter options ~60 ms |
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
| `GET /staffing/ppd` | HPPD. Per facility, the census days between `start_date` and `end_date` (closing census summed, from `daily_payer_census_facts`, once per facility) and, for each of the 23 roles in `shared/staffing.py`, grouped by department, its hours worked, target hours, hours over and short of each day's target, wages, and the wages of the hours over target (`excess_wages`), from `daily_staffing_facts`. The page adds up any set of facilities and roles and divides once: HPPD is hours over census days, target HPPD target hours over the same days, the average rate wages over hours. Over and short hours are counted per facility, role and day, so they never offset each other in a total. 409 unless `staffing_summary` and the net change summary have every day. ~80 ms for 30 days, ~0.4 s for a year (~420 KB) |
| `GET /staffing/ppd/daily` | Each day's census, hours worked and target hours over repeated `roles` and `facility_ids` (the drilldown's), or all, for the HPPD trend; the page sums a period's hours and census before dividing. ~25 ms for 30 days, ~0.45 s for a year |
| `GET /staffing/ppd/trend` | HPPD's Trending tab. Every facility's hours worked, target hours and closing census for each day between `start_date` and `end_date`, over the repeated `roles` (or all), as three arrays per facility aligned to the response's `dates`. The page adds the facilities of any drilldown scope up day by day and divides each day once -- its HPPD, its first and last week, its highest and lowest day, the days over and under target -- and charts the scope's HPPD day over day, always a point per day. Over every role it reads `daily_facility_staffing_facts`, one row per facility and day; for a role subset it reads those roles' rows of `daily_staffing_facts` through the `(role, summary_date)` index and the census from the rollup. PostgreSQL returns each facility's days as arrays (`array_agg` ordered by date), so the service places 253 rows, not 92,000. Measured: ~30 ms for 30 days; for a year ~0.2 s over every role and ~0.3 s for a role subset, against 1.5 s and 3.6 s at the browser before the rollup. 409 unless the staffing, net change and facility staffing summaries have every day |
| `GET /staffing/ppd-cost/trend` | PPD cost's Trending tab. Every facility's total labour cost, budget and closing census for each day between `start_date` and `end_date`, over the repeated `roles` (or every role), as arrays in `dates` order, for the page to add up at any drilldown level and divide day by day. Every role reads the cost columns of `daily_facility_staffing_facts`; a role subset prices those roles' days from the daily tables the same way. The agency premium is priced day by day at that day's in-house rate, so 30 days came to $163,675,841 against the Staffing Overview's $163,672,731, the same $201.15 PPD. Measured: 0.06 s for 30 days and 0.33 s for a year over every role; 0.34 s and 2.7 s for one role. 409 for a day not generated |
| `GET /staffing/employees/packed` | Every employee with hours between `start_date` and `end_date`, compactly, for a Staffing Overview HTML export to carry: facilities listed once and referred to by index, each role's label and department once, and one array per employee (name, facility, role, type, left, termination date, hire date, shifts, hours, wages, overtime hours, holiday premium, bonuses). From the same kept rows as the page (`_rows`): 44,000 employees, about 4 MB, 0.7 s for a range not yet built. The file's script filters, sorts and pages them for its employee windows |
| `GET /staffing/employees` | The Staffing Overview's Employees tab: a page of employees with hours between `start_date` and `end_date` in the repeated `roles` (or all), from `daily_staff_hours`, which keeps only the last 120 days -- the range is clamped to them and the response carries `start_date`, `end_date`, `available_from` and `available_through`. Each row is one person: department, status (`Active`, or `Left` with `termination_date` once it has passed, as of today), whether they are agency, shifts, hours, hours per week, overtime (the stored daily share of each week's hours over 40, summed, as the Overtime report counts it), the overtime and holiday premiums, bonuses (`daily_staff_bonuses`), wages over hours and wages. Takes the log parameters: a JSON `filters` object over `facility`, `state`, `portfolio`, `region`, `department`, `role`, `employment-type`, `status` and `agency`, `search`, `sort`, `direction`, `limit`, `offset`. A range's rows -- one per employee, ~45,000 -- are built once in one statement and kept in the API process for the last four ranges asked for, until the roster, hours or bonuses change (`data_stamp`); the page, its sorts, filters, search, menus and CSV are worked out from them in memory. Each request used to sum the range again: 0.6-1.4 s, 6.7 s sorted by overtime over 120 days. Measured now: ~0.02 s for any page, sort, filter or search and ~0.004 s for a menu once built; building 30 days takes ~0.8 s and the API does it ahead of the first request (`warm`, every five minutes in `main.py`). The hours are stored in date order (`aspire-staff.py`), so a range reads its own days' pages: in staff order, 30 days read every page. 409 before any hours exist or for a range wholly outside the days kept |


| `GET /staffing/employees/filter-options` | One column's menu, from the roster alone (members with hours in the range, under the other filters and the search), never from the sums. `column` is one of the filters above. ~50-550 ms |
| `GET /staffing/employees/export` | The same rows as CSV, every row, overtime included. ~3 s and ~7 MB for 30 days |
| `GET /staffing/agency` | Agency vs In-house. Per facility and role, the hours and wages between `start_date` and `end_date` worked by agency staff and by the facility's own, from `daily_agency_facts`, and the agency premium: what the agency hours cost over the same hours at that facility and role's in-house rate (the roster's average where nobody in-house worked the range), summed by the page and never recomputed from blended rates. Any generated range; 409 past it. ~0.15 s for 30 days |
| `GET /staffing/agency/trend` | Agency vs In-house's Trending tab. Every facility's agency hours, in-house hours and agency wages for each day of the range, as arrays in date order, for the page to add up at any drilldown level and read the agency share day by day. Clamped to the 120 days kept |
| `GET /staffing/overtime` | Overtime. Per facility and role, the hours and wages between `start_date` and `end_date`, the overtime hours, their straight-time pay and the shifts with any, from `daily_overtime_facts`: 0.1 s for 30 days. The premium the page shows is what time-and-a-half would add, half that pay: the facts pay straight time. Any generated range; 409 past it |
| `GET /staffing/overview` | Staffing Overview and PPD. Per facility and role, every measure the pages build their columns from -- census days once per facility; hours worked, budget hours, excess hours, straight-time wages and excess wages; overtime hours and pay; holiday hours and pay (the non-overtime hours on `shared/holidays.py`'s days); agency hours and the agency premium, priced as `/staffing/agency` prices it; new hires, bonuses, agency pay and in-house hours, in-service training hours and pay, and classroom and floor orientation hours and pay -- each role's as an array in the response's `measures` order (0.7 MB, against 2 MB with named fields). Whole months come from `monthly_staffing_cost_facts` and edge days from the daily facts (`rollup_plan`). Measured: 0.53 s for 30 days, 0.62 s for a year, 0.86 s for all history; a year was 5.8 s from the daily facts. Any generated range; 409 past it |
| `GET /staffing/pbj` | PBJ Compliance, one Payroll-Based Journal quarter (`start_date`, `end_date`; CMS fiscal quarters, due 45 days after they end). Per facility: days with residents and resident days (closing census), and weekend resident days; each PBJ role's hours, weekend hours and agency hours (roles mapped to PBJ job title codes 1 and 6-12 in `pbj.PBJ_CODES`; the roster has no code 5 Director of Nursing role); days with residents and no RN hours (4+ a quarter is a one-star Care Compare staffing rating) and with fewer than 8 RN hours; and the facility's own nurses', RNs' and administrators' departures and headcounts over the 12 months to the quarter's end. The page divides once: reported total nurse, RN and weekend HPPD (not case-mix adjusted), turnover, agency share. Measured: 1.7 s for a quarter, first request |
| `GET /staffing/turnover` | Turnover and Retention. Per facility and role, the facility's own employees (agency staff left out) between `start_date` and `end_date`, from the roster's hire and termination dates: headcount the day before the range and on its last day, hires and departures in it, those employed both before and at the end, the hires whose 90th day fell in the range and those of them still employed on it, and the end headcount's days since hire, as arrays in `measures` order. The page divides once: annualized turnover, retention, 90-day retention, average tenure. Start plus hires less departures equals the end headcount at every scope. The roster's dates are drawn up to a year ahead, so a range past the latest generated day is a 409. Measured: 0.06-0.23 s for 30 days to all history, 0.35 MB |
| `GET /staffing/monthly-trending` | Monthly Staffing Trending's five tabs. Per facility and calendar month from `start_month` to `end_month` (YYYY-MM, at most 120), over the repeated `roles` (or all): census days, hours worked, budget hours, labour cost (the PPD cost report's, agency premium priced per facility, role and month), agency and overtime hours, overbudget excess spend and the agency and overtime premiums, each an array aligned to `months` in `measures` order. Read from `monthly_staffing_cost_facts` and, for census, `monthly_payer_census_facts` (equal to the daily facts for all 8,602 facility-months checked). Answers are kept in the process for the last 8 ranges and role picks until a source records a run, and the default 36 months are built ahead by the API's warm-up thread. Measured: 0.43-0.54 s to build 33 months (the rollup query's ~0.3 s is most of it), 0.01-0.04 s kept; 0.67 MB. The page also keeps answers 5 minutes, so its tabs share one request. 409 for a day not generated |
| `GET /staffing/overtime/trend` | Overtime's Trending tab. Every facility's hours, overtime hours and the overtime's pay for each day of the range over the repeated `roles` (or all), as arrays in date order; a day's overtime is its share of each person's overtime for the week, spread over the days they worked |
| `GET /staffing/overtime/logs` + `/filter-options` + `/export` | Overtime's Logs tab: one row per person per day with overtime in the range -- date, person, facility, role, employment type, the day's hours and overtime, rate and premium -- paged, sorted and filtered server-side |
| `GET /staffing/agency/logs` + `/filter-options` + `/export` | Agency vs In-house's Logs tab: one row per agency person per day worked in the range -- date, person, facility, role, first day on the roster, hours, rate and wages -- paged, sorted and filtered server-side; the menus read the agency roster alone. Clamped to the 120 days kept |
| `GET /clinical/fever-infections` | Fever / Infections, an outbreak alert board as of `date` (default the latest day `infection_logs` has). From `infection_logs`, per facility and contagious type (respiratory, influenza-like illness, gastrointestinal), the new cases in the 72 hours and 7 days ending on the day: **Outbreak** at 3+ in 72 hours or 5+ in 7 days, **Watch** at 2 in 72 hours or 3-4 in 7 days. Each alert carries cases with fever, active cases, first and latest onset and the wings affected; totals give facilities in outbreak, on watch (without an outbreak), new cases in 72 hours and active cases, all types. 409 unless the 7 days are generated. ~20 ms |
| `GET /clinical/weight-surveillance` + `/filter-options` + `/export` | Weight Surveillance: everyone in a bed on `end_date` (default the latest day `weight_logs` has), paged, sorted and filtered server-side. From each stay's latest `weight_logs` row in the 30 days to the day: admission, current, highest and lowest weights, change since admission (lb and %), highest to lowest (lb and % of highest), the 30- and 180-day changes, and the MDS flag -- **Significant loss** at -5% in 30 days or -10% in 180, **Significant gain** likewise. The page carries the filtered list's loss and gain counts for the cards. Location menus use a list without weights; the Flag menu builds the full one. ~0.25 s a page |
| `GET /clinical/flagged-notes` + `/filter-options` + `/export` | Flagged Progress Notes: every `progress_notes` row with a watch word, newest first, with its full text for the page's note modal. Filters on facility, location, note type, payer, clinician and flag terms (any of the chosen); search covers the text too. ~0.15-0.25 s a page |
| `GET /mds/pdpm-calculator/facilities` | Every facility with its Original Medicare PDPM contract rate, the base the calculator prices a code against |
| `GET /mds/pdpm-calculator?facility_id=&code=` | The PDPM Calculator: a four-letter code (a five-character HIPPS code is accepted, its indicator ignored) priced at one facility over a full 100-day stay by `shared/pdpm.py` -- each component's share of the contract rate, CMI and 100-day total, every day's rate, the runs of days at one rate (NTA premium, baseline, each taper week), the total, average, day 1 and day 100 rates and the NTA premium. Its total equals `pdpm.stay()` to the cent. No database work beyond the facility's rate, ~4 ms |
| `GET /mds/medicaid-calculator/facilities` | Every Texas facility with its State Medicaid rate, the base the Medicaid Calculator prices a code against |
| `GET /mds/medicaid-calculator?facility_id=&code=` | The Medicaid Calculator: a Texas Medicaid code (nursing letter, cognitive impairment digit, NTA letter) priced at one facility a day and over a 30-day month by `shared/medicaid_pdpm.py`, by component: nursing and NTA shares scaled by the code's CMI against the average resident, a cognitive add-on of 0 to 10% of the base, and a non-case-mix share. The Medicaid Worksheet prices its projected and final codes with the same rule at the stay's plan rate. A demo rule: Texas's own is not modelled, only its shape |
| `GET /mds/pdpm-worksheet/catalog` | The worksheet's cells -- PT/OT primary diagnosis and GG, five SLP parts, nursing category and GG, NTA, projected HIPPS; final HIPPS is not entered but filled on each row from the coded assessment (PDPM code + 1), and both HIPPS codes come priced over a 100-day stay (average, neutral and total revenue, `final_rates` / `projected_rates`) by `shared/pdpm.py`, the formula the data is generated with -- with what each accepts, and the CMS NTA comorbidity list with points |
| `GET /mds/pdpm-worksheet/{payer_stay_id}/entries?field=` | One cell's whole log, entries and replies, oldest first |
| `POST /mds/pdpm-worksheet/{payer_stay_id}/entries` | **Writes.** Appends one entry -- set a value, add or remove an NTA diagnosis, or reply to an entry -- validated against the catalogue, with the signed-in username. The only report route on `DbWriteConnection` |
| `GET /mds/medicaid-worksheet` + `/filter-options` + `/catalog` | The Medicaid PDPM Worksheet: every Texas Medicaid stay whose start, or first assessment's ARD, falls in the range, with Active, how it began and ended, ARD, MDS due (ARD + 14, or Complete once coded), the final two-letter code once coded, and its cells built from the same entry log. Its cells are the Medicare worksheet's nursing and NTA ones plus a projected two-letter code (`projected_code`); no code is priced, since a Texas Medicaid rate is the census day's rate. Page ~90-130 ms for 30 days, ~350 ms for a year |
| `GET` + `POST /mds/medicaid-worksheet/{payer_stay_id}/entries` | One cell's log, and **writes** one entry to `pdpm_worksheet_entries`, the Medicare worksheet's append-only log, validated against the Medicaid catalogue; only a Texas Medicaid payer period takes one. On `DbWriteConnection` |
| `GET /mds/current-medicare/lookback` | Per-facility PDPM resident-days and summed actual and neutral daily rates for today, five single earlier days (yesterday, and the same day a week, a month, 6 months and a year back) and four average periods, as Daily Census defines them, each flagged `average`: last month (the previous calendar month), the last 6 months and the last year (ending yesterday), and all time (first generated day to yesterday), each with its generated days. The page divides once: average daily census is resident-days over days, rates are summed rates over resident-days. Whole months come from `monthly_pdpm_census_facts`; only today and the days of a rollup month outside a period come from the rate steps, about 13 days of them. Today matches `/mds/current-medicare` exactly and every average matched the all-steps query to the cent. ~220 ms, from 1.1 s reading every step; 409 when the rollup is behind the census logs |
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
