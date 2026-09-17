# Report and schema review

Status: proposal for review, not implementation. Audited September 17, 2026.

The later package refactor is described in [the implementation status](backend-refactor-status.md). Original paths and proposed read models below remain a dated audit, not a statement that every optimization has since been implemented.

This is a dated audit, not a permanent inventory or restriction on future work. Recheck implementation claims when using it later. A user request for another module takes priority over the scope described here.

Use [instructions.md](../instructions.md) for development rules. The optimized read paths below are candidates for the audited reports; prototype reports may use explicit source queries until their behavior is settled. References to current behavior mean behavior observed on the audit date, not a continuously maintained status report.

No application edits, database queries, migrations, seed runs, or tests were performed for this review. Findings below come from the routed frontend components and their backend handlers. Latency budgets are proposed acceptance targets, not measured results.

## 1. Scope actually audited

The route dispatch in `frontend/src/app/App.tsx` implements seven reports: Admissions, Discharges, Payer Changes, Net Change, Monthly ADT Trending, Referring Hospital, and Live Census. Monthly ADT has three tabs. Admission/discharge/payer logs, month-overview modals, hospital modals, table-format modals, drilldown totals, and CSV exports are part of those reports.

Five Census entries (Overview, Residents, Bed Board, Daily Trending, Monthly Trending) and all five MDS entries currently render placeholders. Their detailed requirements cannot be verified against a frontend that does not exist. This proposal supplies reusable resident, stay, payer, bed, daily, and monthly data, but does not claim to design MDS assessments, reimbursement, or PDPM from menu names. Those require another report-to-data review when designed.

Unused older components/endpoints are not treated as active requirements. In particular, the removed hospital location tab, payer net-change chart, and movement-logs tab must not silently become new scope.

## 2. Findings in current implementation

| Finding | Evidence | Required change in the proposed design |
| --- | --- | --- |
| Source-filtered Admissions goes back to raw events | `backend/app/adt_admissions.py: admissions_daily_for_sources` builds a grouped admissions subquery when source filters exist | Daily summaries must retain source type, payer, readmissions, 30-day readmissions, and pending-at-admission count together |
| Admissions fetches three hierarchy levels independently | `hooks/useAdmissionsDrilldownData.ts` starts portfolio, region, and facility requests | Return the requested level with shared chart data; avoid three similar scans on every filter change |
| Discharge overview/distributions aggregate raw discharge records | `backend/app/adt_discharges.py: discharge_overview`, `_discharge_distribution` | Shared daily destination/payer/discharge-type measures with LOS numerator and denominator |
| Payer Changes scans events and requests one donut per payer | `backend/app/adt_payer_changes.py`; `PayerChangesOverview.tsx` | Precomputed transition counts; one matrix response supplies every donut |
| Payer-filtered Net Change reconstructs movements and opening census | `backend/app/adt_net_change.py: daily_net_change`, `payer_net_change` | Published daily census by payer type and daily transition pairs |
| Monthly ADT rebuilds months from daily arrays in the browser | `MonthlyAdtTrending.tsx` calls `useNetChangeDaily` and groups days | Read actual monthly records; daily drilldown only when opened |
| Monthly location endpoint still reads raw movements | `adt_net_change.py: monthly_locations` unions admissions/discharges/payer changes | Monthly summaries must serve this endpoint |
| Existing monthly table is populated but not used by active report handlers | `reporting/monthly_activity.py`, route code in `adt_net_change.py` | Creating an aggregate is not enough: every consuming route must explicitly use it |
| Hospital monthly counts are precomputed, but performance is not | `adt_admissions.py: referring_hospital_performance` rebuilds arrays and averages; `ReferringHospitalOverview.tsx` computes labels and modal comparisons | Stored standard performance rows, ranks, and monthly trend; custom subsets use compact summaries |
| Hospital main response includes details it does not display | same hospital handler returns months, receiving lists, and obsolete comparison fields | Compact main rows; fetch one hospital's detail on demand |
| Live Census uses today's close and calculates prior-month AVG on request | `backend/app/live_census.py` | Published current facility snapshot with previous-month average already attached |
| Current bed holds are aggregate demo counts, not resident reservations | `models/bed_holds.py`, `seeding/bed_holds.py` | Resident-linked reservations/absence histories, then derived counts |
| Log searches and facet options can be expensive independently of summary pages | admissions/discharges/payer handlers and `table_filters.py` use exact counts, distinct filters, text casts, offsets, and all-row exports | Indexed event read models, lazy/paged facets, stable pagination, bounded export jobs |
| Current cache is tied mainly to admissions revision | `report_cache.py` | Publication/version keys spanning all dependencies, authorization scope, and effective date |
| Medicaid-pending admissions remain unimplemented | no source status or overview field | Time-qualified status source and precomputed count; cannot infer pending from Medicaid payer |

## 3. Every active display and its proposed read path

Names below refer to the companion `proposed-shared-schema.md`. All reporting tables are shared across modules.

| Active display | Required values and interaction | Proposed source at request time |
| --- | --- | --- |
| Admissions location drilldown | State -> portfolio -> region -> facility -> single facility; total, readmissions, prior equal-length period, difference, distinct hospitals; pending count requested | `admission_source_daily` or its scope/type rollup, exact hospital membership; prepared period rows for default periods |
| Admissions payer donut | Counts per payer type; location/source filters; intentionally ignores its own payer selection so all options remain visible | Same admission daily measures, group by payer type with own filter excluded |
| Admissions source chart | Counts per source type; location/payer filters; intentionally ignores its own source selection | Same measures, group by source type with own filter excluded |
| Admissions trend | 1..60 equal-day bars, preferably >=15 where possible; exact interval and day count | Published daily counts; prepared default chart series, bounded grouping for custom ranges |
| Admissions referring-hospital modal | Exact distinct hospitals and their admission counts; click count -> same filtered logs | `admission_source_daily`, hospital IDs (not name matching) |
| Admissions logs and CSV | Resident, facility/hierarchy, admission date, payer type/plan at admission, source type/name, readmission | `admission_log` with server pagination, authorized exact count and on-demand facets |
| Discharges location drilldown | Counts, average LOS, prior equal period, change, AMA, hospital transfers | `discharge_destination_daily` and scope/type rollup; LOS sums/counts, not averages of averages |
| Discharge payer/destination charts | Cross-filter behavior matching Admissions; destination type and payer can combine | Same discharge cube retaining payer, destination type, and discharge type together |
| Discharges trend | Counts in equal-day blocks | Discharge daily measures |
| Discharges logs and CSV | Resident/hierarchy, admission and discharge dates, payer at discharge, discharge type, destination, LOS | `discharge_log` |
| Payer Changes drilldown | Payer-type change count, affected residents, prior period, difference | `payer_transition_daily` plus exact `payer_change_members_daily` for affected residents |
| Payer transition donuts | For every previous type, destination types/counts; click -> corresponding logs | One precomputed from/to matrix query for the scope/range |
| Payer change logs | Previous/new type and plan, effective date, previous/new payer LOS, ongoing status, numeric LOS filters | `payer_change_log`, published through-date for ongoing LOS |
| Net Change main table | Location, net change, open census, admissions, discharges, close census, unique payer changes; in/out when payer-filtered | `census_daily`, `movement_daily`, `payer_transition_daily`; prepared period rows |
| Net Change trend/tooltip | Net bars; first open, final close, exact dates and day count | Same published daily census/movement; prepared grouped series |
| Net Change table-format modal | One row per day with all main metrics; CSV | Same daily rows, paged for very long ranges; no separate event reconstruction |
| Monthly ADT location table, all 3 tabs | Average/month, highest and lowest month, tied month labels, signed net | `movement_monthly` and standard scope rollups; custom selection extrema calculated after combining monthly series |
| Monthly ADT charts/tooltips | Per-month admissions/discharges/net; average/day; open/close for net; current month MTD | Published monthly measures with covered/expected day counts |
| Monthly ADT table-format modal | Monthly figures, highest/lowest daily values and all ties; payer in/out for net | `movement_monthly`, `monthly_extreme_days`; custom selections aggregate daily summaries before extrema |
| Click any month -> full overview modal | Identical Admissions/Discharges/Net Change overview using selected month, scope, payers; nested logs/hospital modal | Reuse the same report services/read models as standalone pages, with a pinned month and publication |
| Hospital main table | Name, state/portfolio/region, distinct receiving facilities, rank/label, recent average, baseline average, absolute/% difference; name default sort | `hospital_performance_snapshot` for standard scopes/all or one payer type; custom multi-payer response from precomputed totals and membership, cached |
| Hospital modal | 4 KPIs, exactly 27 complete months oldest-first, latest 3 distinguished; receiving facilities/count/performance; payer and facility selection | `hospital_monthly` plus hospital/facility performance rows; one compact modal response; no admission event scan |
| Hospital receiving-facility selection | No selection means all; arbitrary subsets affect KPIs and trend | Sum selected precomputed monthly/count rows, recompute final ratios/category on server, cache; no frontend business-rule fork |
| Live Census drilldown | Current census, occupancy, capacity, empty beds, holds, prior full-month average, difference; no date picker | `current_facility_metrics` and standard scope rows; ratios already prepared; exact as-of/freshness metadata |

### Behaviors the schema must not lose

- Shared table totals must use the correct aggregator: sums for movements, weighted rates for occupancy/LOS, exact unions for hospitals/residents, first/last for census over time, and extrema of the combined series.
- Logs count admission events, not necessarily distinct people. A person may be admitted twice in the interval. Pending-at-admission count uses the same event basis unless the product explicitly requests distinct residents.
- Current payer UI primarily filters **payer types**, not individual insurance plans. Keep both IDs and do not collapse them into one text field.
- Current Payer Changes displays distinct residents **per facility**, then adds those counts at higher levels. That differs from organization-wide distinct people; it needs an explicit approved definition.
- Logs have filters that overview cubes do not need (resident name, exact plan, LOS). They use indexed event projections, not a gigantic all-dimensions aggregate.
- Equal-day trend buckets stay anchored to the selected start date. Retain current divisor preference and short-final-block behavior; do not replace them with calendar weeks/months.
- Zero days/months count only when coverage is complete. Unknown/missing is never silently zero.
- A hospital with no recent activity must remain visible if it was active in the defined 36-month inclusion window.

## 4. What precomputation means here

Three distinct levels are required:

1. **Source histories:** truthful resident/stay/payer/bed records with IDs and time bounds. ETL and fake generation both write this contract.
2. **Published read models:** enriched event logs, current snapshots, daily counts, monthly counts, transition matrices, exact memberships, and standard hierarchy rollups. Built before publication, independently of opening a page.
3. **Prepared report results:** standard period comparisons, hospital performance categories/ranks, table totals and trend buckets. Warm default report requests at publication; store custom results after their first bounded summary query.

A normal SQL view is not precomputation. Expensive interval joins, readmission lookbacks, payer-at-event resolution and live-bed reconciliation belong in the publication jobs, with results stored and indexed.

### Standard views

Store complete hospital performance and live census rows for the organization and each normal hierarchy scope, with ALL payer types and each single type where that report supports it. Store daily/monthly rollups for the same finite scopes. Prepare the default 30-day overview and default 24-month ADT view at publication using the same calculation code as custom queries.

### Custom views

Do not precompute every date-range pair, facility subset, and payer subset. The number of possible combinations grows too quickly and slows publication/storage. On a first custom request:

- Filter and sum the small published daily/monthly tables, never rebuild resident history.
- Apply exact distinct membership where needed.
- Compute final ratios, comparisons, performance category, and combined extrema.
- Cache the finished response by canonical filters, permissions, definition version, and publication.

This is a limited amount of work with an explicit latency budget, not a claim of zero computation. If a cold custom path misses its budget at realistic scale, optimize that path before calling the schema ready.

## 5. Publication, correction, and freshness

- A publication has one coherent source watermark and metric-definition version. All related counts, charts, modals and logs reference it. No mixture of old hospital totals and new logs.
- Build affected output in a transaction or staging generation, validate business invariants, then atomically switch the active publication. Continue serving the last successful publication during preparation.
- Source edits identify dirty facilities/dates and dependent snapshots. Correcting a stay start/discharge can affect readmissions of later stays, payer attribution, LOS, daily census through subsequent periods, monthly rows and any hospital window containing those months.
- Repair a missed seed/ETL date through recorded coverage. Recompute from the earliest affected boundary; do not silently recalculate just today's row.
- Use facility-local reporting dates, explicit timezones, and one documented cutoff. Midnight, same-day admission/discharge, timezone changes and backdated corrections need deterministic behavior.
- Current snapshots refresh after ingest changes. A daily source feed cannot supply real-time data; show its actual as-of timestamp. A UI polling timer does not make the source live.
- Summary completeness is a first-class column, not inferred from positive activity. Source gaps, newly opened facilities, out-of-service beds, and partial current months remain distinguishable from zeros.
- Historical and current hierarchy views must declare attribution. Proposed default for existing drilldowns: today's membership applied to the historical series, matching current frontend behavior. Preserve event-time membership for a future explicit historical-organization view.

## 6. API and frontend work is part of the design

Changing tables alone cannot guarantee fast pages.

- Overview endpoint returns requested drilldown level, correct total, chart distributions, and prepared trend. Avoid fetching every level separately or every payer donut separately.
- Do not fetch modal contents until opened; optional idle prefetch uses an already published cache and does not delay the first table.
- Default hospital response contains only visible table fields and stable IDs. One selected hospital response contains only its requested monthly series, facility rows, and KPI fields.
- Monthly endpoints return months, not years of daily rows. Daily rows are fetched only for custom daily-extrema work or a daily-table drilldown.
- Server returns at most 60 trend points for date-range charts. Rendering code formats values and interactions; it does not maintain a second performance classifier.
- Event logs use stable pagination/order with an ID tiebreaker. Cursor pagination for long lists; bounded page-index support if retained. Count queries and arbitrary substring searches are separate performance paths, not assumed free.
- Reference filter options come from dimension tables; contextual availability/counts use summaries or indexed event projections. Fetch/search/page large resident-name facets on demand, not on every page load.
- CSV exports reuse exact scope/filter/definition/publication. Small exports may stream; large ones use an export job so they do not block interactive database capacity.
- Cache keys include tenant, allowed facility-set hash/authorization version, publication, business date, rules version, filters, sorting and page where relevant. Do not reuse a broader organization's cached totals for a restricted user.
- Return completeness, source_as_of and publication_id. Distinguish empty data, unavailable data, refresh failure, and zero activity.

## 7. Performance budgets to approve and later measure

These are proposed targets, not results from this audit:

| Path | Proposed p95 server budget | Response bound |
| --- | --- | --- |
| Standard overview/live/hospital list | <=250 ms | Visible rows/first page + small chart payload; aim <=200 KB compressed |
| Standard drilldown/modal | <=300 ms | Requested scope; hospital trend 27 months, monthly ADT default 24 months |
| Cold custom facility/payer/date selection | <=500 ms | Published summary queries only; no raw stay/event history scan |
| Log first/next page | <=300 ms | Default 50 rows; at most 100 |
| Filter search | <=250 ms | Searchable/paged options, not every resident |
| First useful page content | <=1 s on the agreed network/device | Includes network, API, parsing and render; loading shell alone does not count |

Before implementation is declared production-ready, agree facility/resident/event volumes, history, concurrent users, update cadence and deployment network. Record cold and warm p95/p99, query plans, publication duration, response sizes and frontend rendering. None of those measurements or tests has been run here.

## 8. Business definitions unresolved at the audit date

Recheck each item against subsequent decisions and current code before treating it as unresolved. Only an ambiguity relevant to the requested change needs clarification; this list is not a gate on unrelated implementation.

1. Census during temporary leave: active census stays vs physically present people. Store both; the live table label must identify which is shown.
2. Capacity denominator: current implementation uses licensed beds. Proposed operational occupancy uses operational beds. Do not change this silently.
3. Empty beds: physical empty beds vs available/unreserved beds. Store both; the current UI subtracts holds.
4. Readmission: same facility or any facility in the group, gap measurement and exactly-30-day boundary. Preserve source flag and derived values separately.
5. Residents affected by payer changes: true distinct people or resident/facility pairs, as noted above.
6. Multi-payer in/out: current code counts transfers between two selected types on both sides (net cancels). Proposed cohort inflow/outflow excludes internal transfers and keeps unique changes separate; approve the display rule first.
7. New/incomplete baseline: keep the current 3 vs preceding 24 complete-month comparison; return insufficient-history status rather than silently dividing partial coverage by 24. Newly active with a known complete zero baseline is a different case.

Report choices recorded at the audit date included no date picker for Live Census and seven hospital performance bands with outer thresholds at +/-20%. These are scoped product choices, not defaults for other reports. Shared seed history, schema parity and refresh rules are maintained in `AGENTS.md` and `instructions.md`.

## 9. Review conclusion

This review covers the implemented surfaces listed in section 3 and identifies their exact summary/event/snapshot inputs. It does not certify measured speed, placeholder report requirements, or a final database without approved metric definitions.

The previous proposal omitted important read paths and exact aggregation cases. The companion schema replaces that proposal and makes the missing work explicit. This review did not authorize a database rewrite or execution. Later implementation follows the user's requested scope; resolve only applicable outstanding definitions rather than requiring blanket approval of this entire historical proposal.
