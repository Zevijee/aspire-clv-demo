# Shared reporting implementation

Implementation status recorded September 17, 2026. The durable ownership rules are in
[instructions.md](../../instructions.md). This describes the current code, not a
closed list of future reports or a requirement to use these grains everywhere.

## Entry points

- `planner.affected_reports` selects reporting dependencies from changed source
  datasets and, optionally, changed fields. Inserts/deletions use structural
  changes rather than a misleading narrow field list.
- `planner.plan_changes` also describes affected date/facility scopes. Supplying
  `retained_through` propagates historical census corrections through retained
  history. Monthly transforms read the whole affected month; coverage records
  still describe the dates the caller actually declares complete.
- `runner.refresh_reports` refreshes explicitly selected reporting nodes over
  existing compatibility event projections. It does not generate source records.
- `runner.refresh_changes` executes the dirty-scope plan and publishes once.
- `runner.refresh_from_canonical` first projects canonical source records into
  the existing serving contracts, then refreshes their dependent reporting. It
  requires an organization, explicit facility codes, complete source inputs, and
  a caller-owned transaction. Unknown source facts that the existing read models
  cannot represent fail explicitly instead of being invented.
- `runner.clear_facility_history` is destructive cleanup for an explicit reset.
  It removes only the selected facility's reporting history and coverage. The
  caller must regenerate and refresh that facility before committing. Ordinary
  refreshes and scoped repairs do not call it.

The independent CLI imports no generator registry. From `backend`, this prints
an offline example plan without accessing the database:

```powershell
python -m reporting --from 2023-09-01 --through 2026-09-17 --preview
```

Execution requires removing `--preview` intentionally. `--dataset` can select a
node; `--include-dependencies` explicitly includes its reporting prerequisites.
`--facility` is repeatable. `--organization` limits ownership. `--from-canonical`
requires both organization and facility scope and refreshes all affected nodes,
so it cannot be combined with a narrower `--dataset` selection. Migrations remain
a separate operation; this CLI never creates or alters tables.

## Implemented serving datasets

| Node | Stored or validated data | Important boundary |
| --- | --- | --- |
| `daily_activity` | Admissions per date/facility/payer; admissions per source combination | Filters absent from a summary can still require an indexed event query. |
| `daily_census` | Dense daily open/close census and movements | Refresh uses persisted stays and events, including quiet dates. |
| `payer_census` | Validates projected payer intervals against daily census and records coverage | This is readiness validation, not a new stored daily payer aggregate. |
| `monthly_activity` | Monthly movements plus first open and last close census | Refresh rebuilds complete affected months from retained daily rows. |
| `referring_hospitals` | Hospital/facility/payer monthly counts, including quiet combinations | Performance comparisons are still calculated from these monthly summaries by the report query. |
| `report_results` | Revision invalidation for a bounded response cache | There are no persistent default-result snapshots or prewarming jobs yet. |

No same-region rule is imposed on real hospital referrals. Regional distribution
of fake referrals belongs to the demo scenario. Hospital identities must still
be mapped before their reporting is refreshed.

## Coverage and publication

New bulk source loads and reporting publication are separate phases. `reporting_source_loads` records loading, sources-complete and complete states and the affected reporting scopes. `python -m reporting --load-id LOAD_ID` consumes a sources-complete load without importing seeding. It groups affected facilities by date interval, builds each required report and commits the publication atomically. Failure leaves sources intact and reporting retryable. The current API returns an explicit unavailable state while any load is pending; historical serving snapshots are not implemented.

Small transactional ingestion can still use `refresh_from_canonical` alongside its source writes. The demo's compatibility adapter resolves residents/stays before completing the source phase. Existing saved version-1 seed runs keep their original recovery semantics; new runs use the two-stage pipeline. Migration 5 adds the load journal and facility-oriented indexes without changing source identities.

`reporting_dataset_coverage` records complete facility/date combinations, including
known zero activity. Global available dates require contiguous covered history
for every facility. A facility reaching a newer day does not advance the global
end date until the remaining facilities are also covered. Migration 4 can retain
previously published compatible coverage under `legacy-published-v3`; new refreshes
record the current rules version.

Admission availability uses this coverage rather than the last positive event.
Payer readiness additionally requires its interval counts to reconcile with
daily census. Hospital publication dates use its own complete coverage. Its
current-month numerator is read from daily source summaries through that exact
published day; completed months use the stored monthly rows. This prevents a
newer partial facility catch-up from changing a numerator under an older divisor.

The response cache includes the business date, request arguments, function/cache
version, and reporting revision. It checks the revision around a computed result
and never caches errors or non-finite JSON numbers. Authorization must be resolved
into explicit scope arguments before using a cached service.

This is an **atomic current publication**. Historical publication rows are not
retained, and a browser cannot pin several separate requests to an older revision.
The compatibility availability records are global, so reporting for another
organization/facility can conservatively wait for the common covered date. Full
tenant-specific publication and authorization are separate remaining work; the
presence of organization IDs does not itself implement user permissions.

No performance benchmark or runtime/database validation has been executed for
this refactor. Cached legacy queries are not thereby classified as fully optimized.
