# Proposed shared schema and report read contract

Review candidate, September 17, 2026. Supersedes the earlier conversational schema. The full proposal is not implemented. See [the refactor status](backend-refactor-status.md) for the shared models and compatibility transition prepared subsequently; no database migration was executed.

This candidate addresses the reports reviewed at that date. It does not require completing them before another module can be built, nor restrict new entities or reports. Adapt it to the user's selected work and current code; proposed steps are not permanent prerequisites.

Implementation follows [instructions.md](../instructions.md): build modules and reports incrementally, allow prototype source queries, and add the proposed read models only as each report is defined and optimized. This document is not an instruction to build every table before continuing product development.

Read `report-schema-audit.md` alongside this file: it maps the report surfaces audited on that date to these tables and lists then-open business definitions. This schema is intended to meet those requirements; measured optimality is not established without production-sized query and concurrency measurements. Mentions of current code, labels and defaults below refer to that snapshot and must be rechecked before implementation.

## A. Ownership and conventions

- Shared source entities and published measures are owned by their data domain, not by whichever UI module first displays them. Add domain-specific tables as new requirements arise without duplicating shared identities.
- Distinguish canonical source tables from stored read projections and aggregates. Derived tables may repeat labels/IDs for fast reads; they are refreshed from canonical IDs and are never independently edited by the seeder or application.
- Use stable internal IDs, not names, as keys. Proposed storage: bigint IDs for compact joins/indexes, with stable source-key mappings. Repeated ingestion must resolve to the same IDs. Exact ID strategy can be changed before DDL if globally generated IDs are required.
- Organization-owned tables include `organization_id`. Tenant-constrained foreign keys prevent references into another organization. Payer-type vocabulary may be shared, but each organization's mapping/overrides must be explicit.
- All temporal histories have start-inclusive/end-exclusive bounds. Use `timestamptz` for actual event times, facility-local `date` for reporting days, `date` at the first of the month for month keys. Do not invent precise event times when a source only provides a day; retain effective date, precision and source ordering.
- Counts use bigint; exact sums and decimal ratios avoid NaN/infinity and floating-point category boundary errors. Rates may be null when no denominator or coverage exists.
- Common canonical metadata columns: `created_at`, `updated_at`, `row_version`, `last_ingestion_run_id` (nullable for manual/reference setup). Externally sourced facts additionally have `source_system_id`, `external_record_id`, `source_updated_at`, `source_deleted_at`; unique `(organization_id, source_system_id, external_record_id)` per fact type. Reference entities may have multiple source aliases through typed mapping tables listed below.
- Common published metadata: `organization_id`, `definition_version`, `publication_id`, `source_as_of`, `completeness_status`. Keys explicitly listed below are within an organization. Published IDs resolve to the same canonical identities.
- Stable keys survive renaming. Deactivate referenced dimensions instead of deleting their history. An edit to a payer name is not a request to regenerate admissions.

## B. Canonical shared source tables

### B1. Organization, hierarchy, capacity and beds

| Table                          | Business columns (in addition to common metadata)                                                                                                                  | Key/relationship                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `organizations`              | `organization_id`, `code`, `name`, `reporting_timezone`, `is_active`                                                                                     | PK organization_id; code unique                                              |
| `portfolios`                 | `portfolio_id`, `code`, `name`, `is_active`                                                                                                                | PK portfolio_id; unique organization/code                                    |
| `regions`                    | `region_id`, `code`, `name`, `is_active`                                                                                                                   | PK region_id; unique organization/code                                       |
| `facilities`                 | `facility_id`, `code`, `name`, `address_line_1`, `address_line_2`, `city`, `state_code`, `postal_code`, `timezone`, `opened_on`, `closed_on` | PK facility_id; unique organization/code; closed_on nullable                 |
| `facility_hierarchy_periods` | `hierarchy_period_id`, `facility_id`, `portfolio_id`, `region_id`, `started_on`, `ended_on`                                                            | FKs to real dimensions; no overlapping hierarchy assignment for one facility |
| `facility_capacity_periods`  | `capacity_period_id`, `facility_id`, `licensed_beds`, `operational_beds`, `started_at`, `ended_at`, `capacity_source`                                | Capacity history; no overlapping official capacity periods                   |
| `rooms`                      | `room_id`, `facility_id`, `code`, `name`, `unit_name`, `opened_on`, `closed_on`                                                                      | unique facility/code                                                         |
| `beds`                       | `bed_id`, `room_id`, `code`, `name`, `opened_on`, `closed_on`                                                                                          | unique room/code; facility resolved through room                             |
| `bed_status_periods`         | `bed_status_period_id`, `bed_id`, `status_code`, `started_at`, `ended_at`, `reason`                                                                    | Operational/unavailable status; occupancy is not a bed status                |

Portfolio/region membership is not assumed globally inferable from names or state. Derived drilldown paths use the full State -> Portfolio -> Region -> Facility tuple. Preserve the actual source hierarchy; do not invent a facility's region from a hospital name.

Licensed capacity and operational capacity are different measures. Bed inventory can validate operational capacity when complete, but incomplete imported bed detail must not overwrite an authoritative facility capacity number. Capacity changes dirty occupancy history for the affected dates. Do not store a single mutable bed count and use it for all historical months.

Demo-only descriptors currently on facilities (acuity, operating maturity, service mix, generation weights) are not report dimensions required by the active views. Put generator-only tuning in versioned demo configuration. Add an actual clinical/service reference entity only when it is part of the source contract, not because a fake generator happens to need a weight.

### B2. Residents and three separate histories

| Table                        | Business columns                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Key/relationship                                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `residents`                | `resident_id`, `first_name`, `last_name`, `display_name`, `date_of_birth`                                                                                                                                                                                                                                                                                                                                                                                                                    | Stable identity; birth date nullable if not provided; do not merge people solely by name                                        |
| `resident_identifiers`     | `resident_identifier_id`, `resident_id`, `source_system_id`, `facility_id`, `identifier_type`, `identifier_value`                                                                                                                                                                                                                                                                                                                                                                          | Source/facility-scoped identifier uniqueness; facility may be null for global source identity                                   |
| `census_stays`             | `stay_id`, `resident_id`, `facility_id`, `admitted_at`, `admission_date`, `admission_time_precision`, `discharged_at`, `discharge_date`, `discharge_time_precision`, `known_from`, `start_known`, `admission_type_id`, `admission_source_type_id`, `admission_source_location_id`, `admission_source_text`, `discharge_type_id`, `discharge_destination_type_id`, `discharge_destination_location_id`, `discharge_destination_text`, `source_readmission_flag` | One continuous admission episode, FK resident/facility/reference values; discharge nullable; unknown initial admission explicit |
| `payer_stays`              | `payer_stay_id`, `stay_id`, `payer_plan_id`, `started_at`, `ended_at`, `effective_start_date`, `effective_end_date`, `time_precision`, `source_sequence`                                                                                                                                                                                                                                                                                                                             | One primary payer/plan interval inside a census stay; referenced plan can be unknown explicitly; FK stay and plan               |
| `resident_bed_assignments` | `assignment_id`, `stay_id`, `bed_id`, `started_at`, `ended_at`, `time_precision`, `source_sequence`                                                                                                                                                                                                                                                                                                                                                                                      | One bed assignment interval; FK stay and bed                                                                                    |
| `resident_absences`        | `absence_id`, `stay_id`, `absence_type_id`, `destination_location_id`, `started_at`, `returned_at`, `time_precision`                                                                                                                                                                                                                                                                                                                                                                     | Temporary leave under an ongoing stay; return nullable                                                                          |
| `bed_reservations`         | `reservation_id`, `bed_id`, `resident_id`, `stay_id`, `absence_id`, `started_at`, `ended_at`, `reason_code`                                                                                                                                                                                                                                                                                                                                                                            | A reservation, not physical occupancy; stay/absence nullable when not applicable                                                |
| `resident_status_periods`  | `status_period_id`, `stay_id`, `status_type_id`, `started_at`, `ended_at`, `time_precision`                                                                                                                                                                                                                                                                                                                                                                                                | Stay-scoped operational status such as Medicaid pending; resident reached through stay                                          |

No independent canonical admissions and discharges duplicate this stay. Their log tables are generated read projections. Ingested event corrections resolve to the same stay and update its appropriate endpoint.

At the first retained day, an existing resident may have been admitted earlier than the extract. Preserve known original admission dates. When unknown, keep an explicit opening cohort with unknown LOS; never fabricate an admission on the window start. `known_from` establishes when coverage starts without claiming that was the admission.

A physical assignment may persist while a resident is absent. The current-bed projection evaluates assignment + absence + reservation together; it cannot infer presence from assignment alone. An occupied bed, held bed, available bed and unavailable bed are disjoint current states. A held bed must not be simultaneously allocated to another resident. Bed belongs to the census stay's facility. Payer/assignment/absence/status periods cannot exceed the applicable stay bounds, except explicit reservation semantics after discharge. These cross-table rules belong in the ingestion/publication contract and constraints where possible.

### B3. Payer and location references

| Table                             | Business columns                                                                                                                                            | Notes                                                                                                             |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `payer_types`                   | `payer_type_id`, `code`, `name`, `is_active`                                                                                                        | The business categories shown by the existing filters                                                             |
| `payers`                        | `payer_id`, `code`, `name`, `is_active`                                                                                                             | Insurer/payer identity                                                                                            |
| `payer_plans`                   | `payer_plan_id`, `payer_id`, `payer_type_id`, `code`, `name`, `is_active`                                                                       | Product/plan; same insurer can have plans in different types; Private Pay can use an explicit self-pay definition |
| `location_types`                | `location_type_id`, `code`, `name`, `is_active`                                                                                                     | Hospital, Home, Skilled Nursing, etc.                                                                             |
| `external_locations`            | `location_id`, `location_type_id`, `code`, `name`, `address_line_1`, `address_line_2`, `city`, `state_code`, `postal_code`, `is_active` | Hospitals and other named admission/discharge locations, shared by both movements                                 |
| `external_location_assignments` | `assignment_id`, `location_id`, `portfolio_id`, `region_id`, `started_on`, `ended_on`                                                           | Reporting territory; does not prohibit real referrals across territories                                          |
| `admission_types`               | `admission_type_id`, `code`, `name`, `is_active`                                                                                                    | Source admission classifications                                                                                  |
| `discharge_types`               | `discharge_type_id`, `code`, `name`, `is_active`                                                                                                    | Routine, Transfer, Deceased, AMA                                                                                  |
| `absence_types`                 | `absence_type_id`, `code`, `name`, `is_active`                                                                                                      | Hospital leave, personal leave, etc.                                                                              |
| `resident_status_types`         | `status_type_id`, `code`, `name`, `is_active`                                                                                                       | Medicaid pending etc.                                                                                             |

For source aliases use typed tables `facility_source_keys`, `payer_source_keys`, `payer_plan_source_keys`, `payer_type_source_keys`, `external_location_source_keys`, `portfolio_source_keys`, `region_source_keys`. Each has its own mapping ID, canonical entity FK, source_system_id, external_key, and unique source/key within the organization. Other low-cardinality classifications use equivalent typed mappings when imported values differ. This replaces the earlier suggestion of an untyped entity ID in a universal source-links table, which would not enforce its target FK.

Payer type changes and plan-only changes are distinct. They are derived from adjacent payer intervals and labeled in one rules implementation. Historical reclassification of a plan's type must be an explicit restatement with affected summaries refreshed; a label-only rename is not reclassification. If classifications change prospectively, represent a new effective plan definition rather than silently recategorizing prior events.

At review time, Commercial Medicare and Medicare HMO were requested reference labels, and a hidden `Medicare Advantage` display remapping remained. If that remapping still exists when these references are migrated, resolve it through an explicit code-to-ID mapping using the then-current reference contract. These names are not a fixed payer catalog.

## C. Stored event and current-state read models

These are physical, indexed projections, not expensive views executed for every request. Each carries common publication metadata and canonical foreign-key IDs. Text labels may be copied for indexed searching but never serve as identity. Scope and authorization apply on the server before counts, caches or exports.

### C1. Event logs

`admission_log`, one row per known admission:

```text
stay_id (key), resident_id, facility_id, event_at, event_date,
resident_display_name, current_scope_id, event_scope_id,
payer_stay_id, payer_plan_id, payer_type_id,
source_type_id, source_location_id, source_display_name,
previous_stay_id, previous_discharge_date, readmission_gap_days,
source_readmission_flag, is_readmission, readmission_within_30_days,
readmission_gap_known, medicaid_pending_at_admission,
search_document
```

`discharge_log`, one row per discharge:

```text
stay_id (key), resident_id, facility_id, event_at, event_date,
resident_display_name, current_scope_id, event_scope_id,
admission_date, payer_stay_id, payer_plan_id, payer_type_id,
discharge_type_id, destination_type_id, destination_location_id,
destination_display_name, los_days, los_known, is_ama,
is_hospital_transfer, search_document
```

`payer_change_log`, one row per adjacent coverage transition:

```text
transition_id (key), stay_id, resident_id, facility_id,
event_at, event_date, source_sequence, current_scope_id, event_scope_id,
previous_payer_stay_id, new_payer_stay_id,
previous_plan_id, new_plan_id, previous_type_id, new_type_id,
change_category, previous_started_at, new_started_at, new_ended_at,
previous_los_days, new_los_days, new_los_ongoing, los_as_of_date,
resident_display_name, search_document
```

Ongoing LOS advances at the reporting date rollover even when there are no new admissions. Date-only records use calendar-day rules matching the current UI, not elapsed-hours division. Resolve payer at admission/discharge from the documented boundary rule once during publication; retain the resolved payer_stay_id for explanation.

`bed_move_log`, one row per bed transition (shared source for future bed history):

```text
move_id (key), stay_id, resident_id, facility_id,
previous_assignment_id, new_assignment_id, previous_bed_id, new_bed_id,
event_at, event_date, source_sequence
```

### C2. Current projections

`current_resident_state`, key resident_id within organization:

```text
resident_id, stay_id, facility_id, current_scope_id,
admitted_at, admission_date, census_los_days, census_los_known,
payer_stay_id, payer_plan_id, payer_type_id, payer_started_at, payer_los_days,
assignment_id, bed_id, absence_id, reservation_id,
is_present, is_medicaid_pending, as_of_at
```

Require nonoverlapping active census stays for one person within the organization, with explicit transfer boundaries. Conflicting source data is flagged, not resolved by arbitrarily taking one row. If concurrent legitimate stays later become a requirement, the key and UI must explicitly change.

`current_bed_state`, key bed_id:

```text
bed_id, facility_id, room_id, state_code,
occupant_stay_id, reservation_id, as_of_at
```

State values: occupied, held, available, unavailable. Unknown inventory coverage is a completeness issue, not a fabricated available bed.

`current_facility_metrics`, key scope_id (facility and finite standard ancestor scopes):

```text
scope_id, business_date, as_of_at, active_census, physically_present,
occupied_beds, licensed_capacity, operational_capacity,
physical_empty_beds, held_beds, available_beds, unavailable_beds,
census_occupancy_pct, physical_occupancy_pct,
previous_month, previous_month_expected_days, previous_month_covered_days,
previous_month_census_day_total, previous_month_average_census,
previous_month_present_day_total, previous_month_average_present,
census_variance, physical_presence_variance
```

Store the numerator/denominator and the prepared displayed ratio. Summarize scope-level live snapshots during publication. This makes every standard Live Census drilldown a small fetch, with the approved display definition selected consistently.

## D. Daily and monthly aggregate contract

### D1. Scope and payer selectors

`reporting_scopes`:

```text
scope_id, organization_id, level (organization/state/portfolio/region/facility),
parent_scope_id, state_code, portfolio_id, region_id, facility_id, label,
membership_revision
```

`reporting_scope_members`:

```text
scope_id, facility_id, membership_revision  (composite key)
```

These are derived from the approved current hierarchy, not another independently maintained organization tree. Use full path identity so equal labels in two states do not merge. Facility and organization scopes use the same contract. Historical event-time membership remains in source history and event projections; the default existing UI uses current membership.

`reporting_payer_selections`:

```text
payer_selection_id, kind (ALL/TYPE/UNKNOWN), payer_type_id
```

Enforce exactly one ALL and UNKNOWN entry, unique TYPE per ID, and kind/ID consistency. ALL is not the same as null/unknown payer. It is a rollup selector, never a real payer assigned to a resident. Multi-select combinations are canonicalized request parameters/cache keys, not permanent payer dimension rows.

### D2. Base tables and columns

Every date is a facility-local reporting date. Every base table below retains facility_id, even when ancestor rollups are built. Dense rows for low-cardinality census/coverage; sparse nonzero combinations for sources/destinations/transitions. Known absent sparse combinations count as zero only when coverage says complete.

| Table                           | Row key / grain                                                                                                    | Measures                                                                                                                                                                                                                                                                                      |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `movement_daily`              | facility_id, date, payer_selection_id                                                                              | admissions, discharges, net_change, readmissions, readmissions_within_30, readmissions_unknown_gap, medicaid_pending_admissions, discharge_los_sum, discharge_los_known_count, ama_discharges, hospital_transfers, payer_type_changes, plan_only_changes, returns_from_leave, starts_of_leave |
| `census_daily`                | facility_id, date, payer_selection_id                                                                              | open_census, close_census, open_present, close_present, active_census_day_value, present_day_value, coverage_start_at, coverage_end_at, is_complete                                                                                                                                           |
| `bed_inventory_daily`         | facility_id, date                                                                                                  | licensed_capacity, operational_capacity, occupied_beds, held_beds, available_beds, unavailable_beds, physical_empty_beds, snapshot_at, is_complete                                                                                                                                            |
| `admission_source_daily`      | facility_id, date, payer_type_id/unknown, source_type_id, source_location_id/unknown                               | admissions, readmissions, readmissions_within_30, readmissions_unknown_gap, medicaid_pending_admissions                                                                                                                                                                                       |
| `discharge_destination_daily` | facility_id, date, payer_type_id/unknown, discharge_type_id, destination_type_id, destination_location_id/unknown  | discharges, discharge_los_sum, discharge_los_known_count, ama_discharges, hospital_transfers                                                                                                                                                                                                  |
| `payer_transition_daily`      | facility_id, date, previous_type_id, new_type_id, change_category                                                  | transition_count                                                                                                                                                                                                                                                                              |
| `payer_change_members_daily`  | facility_id, date, resident_id                                                                                     | payer_type_change_count                                                                                                                                                                                                                                                                       |
| `source_monthly`              | facility_id, month, payer_type_id/unknown, source_type_id, source_location_id/unknown                              | same admission-source counts, expected_days, covered_days                                                                                                                                                                                                                                     |
| `destination_monthly`         | facility_id, month, payer_type_id/unknown, discharge_type_id, destination_type_id, destination_location_id/unknown | same discharge counts and LOS accumulators, expected_days, covered_days                                                                                                                                                                                                                       |

Unknown source/location dimensions need explicit typed unknown members or a unique-null key policy in DDL; do not let nullable composite keys admit duplicates. An unknown location is not one giant fictional hospital included in distinct-hospital counts.

`movement_monthly`, grain facility_id, month, payer_selection_id:

```text
month_start, through_date, expected_days, covered_days, is_complete_month,
admissions, discharges, net_change, readmissions, readmissions_within_30,
readmissions_unknown_gap, medicaid_pending_admissions,
ama_discharges, hospital_transfers, discharge_los_sum, discharge_los_known_count,
open_census, close_census, open_present, close_present,
census_day_total, present_day_total, average_census, average_present,
average_admissions_per_day, average_discharges_per_day, average_net_per_day,
payer_type_changes, plan_only_changes,
admissions_highest_day_value, admissions_lowest_day_value,
discharges_highest_day_value, discharges_lowest_day_value,
net_highest_day_value, net_lowest_day_value
```

For ALL, payer_type_changes counts each transition once. For TYPE, it counts each event touching that type once; these columns must not be summed to produce ALL or a multi-type unique count. Selected-cohort in/out are prepared from the transition-pair matrix, not by summing a misleading per-type column.

`monthly_extreme_days`:

```text
scope_id, month, payer_selection_id, metric (admissions/discharges/net_change),
extreme (highest/lowest), value, date  (one row per tied date)
```

`payer_transition_monthly`: same pair grain and transition_count as the daily table, replacing date with month. Supports type-filtered monthly in/out and unique-change totals without event reads.

### D3. Finite hierarchy rollups

Create the following stored rollups at publication for standard organization/state/portfolio/region scopes. Facility reads use the base rows. The same table family is shared by all modules.

- `scope_movement_daily`: movement_daily measures, keyed by scope/date/payer selection.
- `scope_census_daily`: census_daily measures, keyed by scope/date/payer selection, with explicit member-coverage counts.
- `scope_movement_monthly`: movement_monthly measures, keyed by scope/month/payer selection; compute daily extrema from aggregated daily series, not facility extrema.
- `scope_admission_type_daily`: admission_source_daily measures, keyed by scope/date/payer type/source type. Distinct source locations use source membership separately.
- `scope_discharge_type_daily`: discharge measures, keyed by scope/date/payer type/destination type/discharge type.
- `scope_payer_transition_daily` and `scope_payer_transition_monthly`: transition-pair measures for scope/day or month.

No dense product of all residents, beds, payers, sources and dates. Build rollups for defined consumers and their query needs, including reports, exports and other requested workflows. Deduplicate selected facility membership before aggregating overlapping hierarchy selections.

For custom cross-facility views, use base rows rather than adding overlapping ancestor rollups. Exact totals and rates are computed from common denominators after unioning the facilities.

## E. Precomputed hospital monthly performance

`hospital_monthly` is a stored hospital-only projection of `source_monthly`:

```text
hospital_id, scope_id, month, payer_selection_id,
admissions, readmissions, readmissions_within_30,
expected_days, covered_days, is_complete_month
```

It has both facility rows and standard ancestor rows. This is deliberate serving duplication, generated from the same admission-source data, not a second hospital truth.

`hospital_receiving_members_monthly`:

```text
hospital_id, facility_id, month, payer_type_id, admissions
```

Keep positive membership/counts. Exact receiving-facility unions over a period or multiple types come from this compact relation, not summing distinct-facility counts.

`performance_policies`:

```text
policy_id, version, name, recent_complete_months, baseline_complete_months,
inclusion_months, growth_outer_pct, growth_middle_pct, growth_inner_pct,
decline_outer_pct, decline_middle_pct, decline_inner_pct,
zero_baseline_behavior, incomplete_history_behavior
```

Hospital policy recorded at review time: recent 3 complete months vs preceding 24 complete months; 36-month hospital inclusion history; thresholds +/-5%, +/-10%, +/-20%. These are versioned report-policy values, not universal performance definitions. Publication and custom-result calculations use the same applicable policy; the browser does not implement a separate classifier.

`hospital_performance_snapshot`, grain hospital_id, scope_id, payer_selection_id, as_of_month, policy_id/version:

```text
recent_start_month, recent_end_month, baseline_start_month, baseline_end_month,
inclusion_start_month, inclusion_end_month,
recent_admissions, recent_expected_months, recent_covered_months,
baseline_admissions, baseline_expected_months, baseline_covered_months,
recent_average, baseline_average, difference, difference_percent,
performance_code, performance_rank, receiving_facility_count,
referrals_in_inclusion_window, admissions_in_display_window,
has_complete_history, assigned_state_code, assigned_portfolio_id, assigned_region_id
```

The scope_id may be one receiving facility: those rows directly serve the modal's facility-performance column. For all facilities/one type or ALL, the main table and four modal KPIs fetch stored values. The 27 chart bars come straight from hospital_monthly, not resident history.

Classification boundaries recorded for this hospital policy:

| Code                 | Condition                                                                         |
| -------------------- | --------------------------------------------------------------------------------- |
| Strong growth        | >= +20%                                                                           |
| Growing              | >= +10% and < +20%                                                                |
| Slight growth        | >= +5% and < +10%                                                                 |
| Stable               | > -5% and < +5%                                                                   |
| Slight decline       | > -10% and <= -5%                                                                 |
| Declining            | > -20% and <= -10%                                                                |
| Sharp decline        | <= -20%                                                                           |
| New/returning        | complete baseline is zero and recent > 0                                          |
| No recent activity   | complete baseline and recent both zero, matching current code's special case      |
| Insufficient history | required baseline/recent coverage is not complete; new explicit data-quality case |

For a custom multi-payer/facility subset, sum precomputed recent/baseline numerators with matched complete periods, derive the ratio/category once, and union receiving facility IDs. Cache the finished result. Never average constituent performance percentages or choose a category by voting.

Main-list eligibility is separate from performance: a hospital with referrals in the inclusion window must remain visible even if its latest 27 months are zero. Confirm whether MTD-only new hospitals join the list; current code includes them even though the comparison uses complete months.

## F. Exact aggregation rules and stored results

### F1. Non-additive measures

- **Distinct hospitals:** exact distinct hospital IDs in admission_source_daily for the selected dates/facilities/types. Default report rows store the finished count. Do not add facility-level distinct counts.
- **Residents affected:** exact resident IDs from payer_change_members_daily; or exact (resident, facility) pairs if preserving the current per-facility definition. Monthly/daily distinct counts cannot be added across time. This compact member relation is needed even with precomputed totals.
- **Unique payer changes for selected types:** sum transition_count where previous type OR new type is selected; each pair row counted once. No division by two and no sum of in/out as a proxy.
- **Cohort payer inflow:** previous type outside selection and new type inside. Outflow is the reverse. Internal selected-to-selected transitions do not change cohort census. If current gross in/out display is retained, calculate and name that separately.
- **Highest/lowest day:** first sum each day's metric over the selected group, then take min/max and all tied dates. A facility's minimum alone is insufficient to compute a group's minimum.
- **Census:** additive across disjoint facilities at the same cutoff, never across time. Period boundaries use first open and last close. Movement balance includes defined leave effects if displaying physical presence rather than active stays.
- **Average LOS:** sum known LOS / count with known LOS. A missing original admission does not become zero LOS.
- **Average census / occupancy:** preserve census-day totals and covered days; aggregate scope daily totals using a consistent calendar, then average. Occupancy uses summed eligible numerator/capacity, not an average of percentages.
- **MTD:** through-date explicit. Do not quietly compare a partial current month as a full month. Existing monthly table includes selected MTD as one selected month; preserve and label that unless changed.

### F2. Prepared report results

`report_result_sets`:

```text
result_set_id, organization_id, publication_id, report_kind,
scope_id, authorized_scope_hash, definition_version,
start_date, end_date, prior_start_date, prior_end_date,
canonical_filters, filter_hash, is_prepared_default,
prepared_at, expires_at, row_count, completeness_status
```

`report_result_rows`:

```text
result_set_id, row_key, row_scope_id, sort_ordinal,
metrics_payload, is_total
```

`report_result_series`:

```text
result_set_id, series_key, point_ordinal, start_date, end_date, day_count,
metrics_payload
```

These payloads are typed/versioned by report_kind in the API contract; they are a serving cache, not source facts or a place for SQL analytics. Hospital standard performance and live census remain typed column tables because they need server sorting/filtering by measures.

Prepare the default 30-day admissions/discharges/net/payer-change requests and 24-month Monthly ADT requests for standard scopes at publication; use the same calculation code as custom requests. Also prepare ALL and individual payer types where used. Do not prepare every arbitrary source/destination/payer subset. Result keys capture default dates explicitly so tomorrow cannot reuse yesterday's relative-date result.

Custom cache misses read only published summaries/member relations. Event projection reads are permitted for log/search requests. Expensive reconstruction of original histories is prohibited on interactive overview routes.

## G. Ingestion, publication and seed control tables

| Table                              | Columns / responsibility                                                                                                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source_systems`                 | source_system_id, organization_id, code, name, source_timezone, is_active                                                                                                             |
| `ingestion_runs`                 | ingestion_run_id, source_system_id, started_at, finished_at, status, requested_from, requested_through, source_watermark_from, source_watermark_to, error_summary                     |
| `ingestion_checkpoints`          | source_system_id, dataset, facility_id/scope, committed_watermark, ingestion_run_id; persisted only after successful publication                                                      |
| `data_coverage`                  | source_system_id, facility_id, dataset, date, coverage_start_at, coverage_end_at, status, expected_complete, ingestion_run_id                                                         |
| `ingestion_issues`               | issue_id, ingestion_run_id, dataset, external_record_id, code, severity, detail, resolved_at; invalid source facts never silently become zero activity                                |
| `metric_definitions`             | definition_version, approved_at, configuration, effective_at; readmission, LOS, census/leave, hierarchy, completeness and boundary rules                                              |
| `reporting_publications`         | publication_id, organization_id, status, source_as_of, definition_version, started_at, published_at, covered_from, covered_through                                                    |
| `active_reporting_publication`   | organization_id, publication_id; one active completed revision                                                                                                                        |
| `reporting_refresh_tasks`        | task_id, dataset, facility_id, affected_from, affected_through, reason, ingestion_run_id, status, publication_id; deduplicated dirty work                                             |
| `report_result_sets/rows/series` | as defined above; bounded, revision-aware prepared/custom response storage                                                                                                            |
| `export_jobs`                    | export_job_id, organization_id, requester_id, authorization_scope_hash, result_kind, filters, publication_id, status, started_at, finished_at, row_count, output_location, expires_at |
| `schema_migrations`              | version, applied_at, checksum                                                                                                                                                         |
| `seed_runs`                      | seed_run_id, operation, requested_datasets, from_date, through_date, generator_config_version, started_at, finished_at, status, error_summary                                         |
| `seed_dataset_state`             | dataset, generator_version, input_fingerprint, last_successful_seed_run_id                                                                                                            |
| `seed_coverage`                  | dataset, seed_date, row_count, generator_version, seed_run_id                                                                                                                         |

This review did not establish an authorization identity/role schema. The reporting contract accepts effective authorized facility IDs from that system. Resolve requester_id to the actual identity model when implementing it; absence from this review does not imply that the application still lacks that model.

## H. Index and publication requirements

Index intent, to turn into concrete DDL after size estimates:

- Canonical facts: unique source identity; (resident_id, effective start) and (facility_id, effective date); FK indexes. Temporal overlap constraints for primary coverage, hierarchy assignments, and bed occupancy/reservations with agreed leave rules.
- Event projections: (organization_id, event_date, event_id), (organization_id, facility_id, event_date, event_id), and measured composite indexes for payer/source/destination filters. Resident lookup via resident_id. Search_document needs an indexed search strategy that preserves the UI's desired substring behavior; do not rely on casts of every column. Extension choices are implementation decisions, not prerequisites hidden in the schema.
- Daily: unique grain, indexes beginning with organization/facility/date or organization/scope/date; additional payer/source-leading index only where actual plans justify it.
- Hospital monthly: (organization_id, hospital_id, scope_id, payer_selection_id, month); performance list indexes for hospital name and performance_rank within publication/payer selection; membership index on hospital/month/facility/type.
- Current: primary resident, facility and bed lookups plus active scope indexes; no scan of years of stays on page load.
- Partition high-volume event/daily tables by month only when measured volume/maintenance justifies it. Do not partition tiny reference/current tables or multiply partitions per payer/facility without evidence.
- Use a single atomic source/read-model publication or staged affected partitions with an atomic active revision switch. Background generation never exposes half-updated sources/summaries.
- Each request uses one published revision in one consistent read. Related modal requests carry publication_id. If that revision is no longer retained, return an explicit refresh-required response and reload together; do not combine new logs with an old parent total. Retained versions/caches have bounded lifetime, not unlimited full-history duplication.
- Source labels, hierarchy changes and permission changes invalidate appropriate result caches even if no admission changed.

### Storage and refresh cost must be budgeted too

Let F be facilities, D covered days, T payer types plus ALL/UNKNOWN, M covered months, and S finite hierarchy scopes. Dense facility census/movement storage grows roughly with F x D x T; monthly storage with F x M x T. Scope rollups add S x D x T and S x M x T. These are separate from sparse source/destination and transition pairs, whose size depends on combinations actually observed.

Do not build hospital x every scope x every payer x every month regardless of relationships. Store observed hospital/receiving-facility relationships, their ancestor rollups, and explicit eligibility/coverage so known quiet months can be returned as zero. A 36-month inclusion history does not require sending 36 months in each main-list row.

For deployment sizing, estimate row counts, bytes per row/index, refresh work per ingest batch, retained result sets and query concurrency at expected scale plus agreed headroom. A cache cannot rescue a cold query that scans unbounded source history, and excessive eager precomputation can itself delay the next publication.

Prewarm a bounded set of defaults for standard authorized scopes. Do not generate every possible role/facility permission subset; unusual authorized selections use compact summaries and a permission-scoped cache. Version old outputs only for a bounded consistency window.

## I. Seeder contract against this schema

The generator and ETL are separate writers of the same source contract. The shared publication pipeline builds all derived records. Seeders do not fill hospital aggregates with unrelated fake numbers.

Dependency examples for the source families covered by this proposal. A scoped operation follows only its relevant dependencies; unrelated domains need not be implemented or regenerated:

```text
references and hierarchy -> residents and identity mappings -> census stays
                         -> payer stays / bed assignments / absences / reservations / statuses
                         -> event and current-state projections
                         -> daily measures and exact memberships
                         -> monthly measures and scope rollups
                         -> hospital performance / live metrics / prepared default results
                         -> atomic publication
```

- Update/reference rename is independent from historical regeneration. Add a payer type/plan without rebuilding stays. Assigning that new plan to demo history is a separate explicitly scoped coverage-generation operation.
- Support `update`, `rebuild` and `refresh` per dataset with a preview dependency plan. Rebuilding derived reports never generates different residents. Rebuilding payer histories refreshes payer-at-admission/discharge, payer movements/census, logs and affected summaries, but does not create new admission identities/dates.
- Bed/reservation generation uses real beds and stay/absence relationships. Holds are not arbitrary counts attached afterward. Changing bed history refreshes bed/current projections, not payer identities.
- Generate missing dates using shared SeedWindow; first day of month 36 months before as-of through as-of inclusive. Preserve complete months, MTD, known zeros and pre-window opening state. Generate stable identities; no truncated-history fake admission dates.
- Demo time precision must match its generated facts; do not assert real-time accuracy for date-only daily generation.
- Daily catch-up runs advance current/ongoing LOS and period comparisons as well as source activity. Missed days are recovered from coverage/checkpoints.
- Record source generator versions separately; changing a label alone must not force admissions-daily-v5 and a full rebuild.
- Only commit completion records/watermarks after dependent publications reconcile. Failed or cancelled runs leave the last completed revision usable.
- Validate movement balances, payer coverage, bed exclusivity, scope totals, source totals, complete-month windows and log-to-summary reconciliation as publication invariants. This describes future ingestion guards; no tests are added or run in this review.

## J. Implementation scope

This is a candidate design for the seven reports audited in September 2026, not a complete design for all future modules. The proposal itself authorizes no migrations, data changes or full refactor. A subsequent user request determines what to implement or execute. Check only the relevant decisions and actual dependencies for that scope; do not make approval or completion of every table and report in this document a prerequisite for new work.
