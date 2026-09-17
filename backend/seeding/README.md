# Demo seeding

Implementation inventory recorded 2026-09-17. These capabilities and limitations describe this version; they are not restrictions on future modules or scenario work. The durable rules are in [instructions.md](../../instructions.md).

The refactor was prepared in code. No migration, seed, backfill, database inspection, service, or test was executed as part of preparing it. Commands below are operator examples, not a record of execution.

## Ownership

- `cli.py`: explicit commands; offline preview does not open a database connection.
- `planner.py`: selected datasets, exact requested scope, prerequisite verification, downstream source reconciliation and report dependencies.
- `runner.py` / `phased.py`: dependency-ordered source stages, checkpoints, run records, failures and resume.
- `source_pipeline.py`: read-only scenario planning followed by shared resident/stay writes. Durable plans preserve resolved identities across retries.
- `generators/`: deterministic fake identities and movement/coverage scenarios. New loads write canonical residents, census stays and payer stays before their ADT compatibility records. `data.writers.legacy` remains for explicit old-data backfills and old-run recovery.
- `reference_data/`: versioned demo facilities, hospitals and stable payer codes/aliases with separate editable labels.
- `scenarios/`: arrival volumes, coverage distributions and identity-generation parameters.
- `state/`: database target protection and transactional boundaries/completion records.
- `reporting/` (sibling package): calculations, summaries, coverage and publication. Reporting refresh does not invoke a fake-data generator.

No generator creates tables, applies migrations, opens an engine, or commits its own transaction. Old `app.seeding` paths and old seed entrypoints are compatibility imports/launchers.

## Explicit setup

Schema upgrades and demo-target registration are separate operations. Use the same migrations for demo and production. To authorize a database for fake generation, configure `ENVIRONMENT=development` or `demo` and a nonempty `DEMO_INSTANCE_ID` in the local environment, then explicitly register that identity. Production environments are refused even if the database name resembles a demo.

From `backend`, using the project's backend Python environment:

```powershell
python -m data.migrations upgrade --preview
python -m data.migrations configure-demo --instance-id YOUR_LOCAL_DEMO_ID --preview
```

Remove `--preview` only when intentionally applying the schema or recording the demo identity. The configured instance ID, the database identity row and the actual database name must agree. Generation never claims a database automatically.

From the repository root, `python seed_data.py ...` launches the same commands as `python -m seeding ...` from `backend`. The process remains owned by that terminal.

## Commands

Examples below use `--preview` for mutation plans. A preview lists the source order, reporting order, requested facility/entity scope, versions and replay semantics. `--inspect` explicitly allows read-only database inspection; plain preview stays offline.

```powershell
python seed_data.py preview
python seed_data.py inspect --dataset admissions --facility ASP-001
python seed_data.py inspect --run-id RUN_ID

python seed_data.py update --through today --preview
python seed_data.py populate --dataset admissions --facility ASP-001 --preview
python seed_data.py rebuild --dataset admissions --facility ASP-001 --from 2026-09-01 --through 2026-09-17 --preview

python seed_data.py update --dataset payers --changed-field name --preview
python seed_data.py update --dataset facilities --facility ASP-001 --changed-field name --preview

python seed_data.py backfill --backfill-name canonical_sources --facility ASP-001 --preview
python seed_data.py backfill --backfill-name hospital_assignments --facility ASP-001 --from 2026-09-01 --through 2026-09-17 --preview
python seed_data.py backfill --backfill-name initial_payer --facility ASP-001 --preview

python seed_data.py refresh --dataset referring_hospitals --facility ASP-001 --preview
python seed_data.py resume --run-id RUN_ID --preview
python seed_data.py full-reset --preview
```

To execute a generation/backfill command, intentionally remove `--preview` and supply `--demo-instance YOUR_LOCAL_DEMO_ID` or matching `DEMO_INSTANCE_ID`. `resume` uses the stored immutable plan; do not pass replacement datasets, dates or versions. Offline resume preview identifies the requested run without fetching it. Use `inspect --run-id ...` to read its recorded plan and batches.

For production-capable reporting refresh, use the independent `python -m reporting` CLI. It has no demo-target requirement or generator dependency. The seed CLI's `refresh` operation remains guarded as a demo management command.

## Available source datasets

| Dataset | Owned work | Prerequisites |
| --- | --- | --- |
| `states` | Shared state code/name references for the demo locations | None |
| `portfolios` | Shared organization portfolio records | Creates the demo organization if missing |
| `regions` | Shared organization region records | Portfolio references |
| `facilities` | Demo facilities and hierarchy assignments | States, portfolios and regions already exist or are explicitly selected |
| `hospitals` | Demo hospital references for selected facility regions | Facilities already exist or are explicitly selected in the same plan |
| `payers` | Organization-wide payer type/plan references and labels | Demo organization created by the reference operation |
| `admissions` | Missing daily admission partitions | Facilities/hospital references; downstream stays, coverage and holds are explicitly included in the plan |
| `discharges` | Resident-stay simulation, discharge events and daily census | Complete admission history |
| `payer_changes` | Payer intervals and transitions for affected stays | Complete stays/census history |
| `bed_holds` | Demo daily reserved-bed counts | Complete stays/census history |

Dependencies are not permission to generate every ancestor. Selecting `payer_changes` does not quietly regenerate admissions. A missing prerequisite stops execution with an actionable message. Reference label updates have no source-history generator descendants. New payer definitions do not redistribute historical payers.

Named backfills:

- `canonical_sources`: preserve existing UUIDs while writing legacy source facts into shared resident/stay/reference/coverage tables; no fake generation.
- `hospital_assignments`: change only selected hospital admission source assignments using the registered demo scenario; dates/resident identities remain unchanged. Optional `--entity` values are admission IDs and must belong to the selected scope.
- `initial_payer`: fill missing initial payer values from the corresponding admission; unrelated source fields are retained.

## Scope and history

- All date-based generation uses 36 complete calendar months plus the current month through the explicit as-of date. `--history-months` accepts 36 and `--history-years` accepts 3; neither shortens the contract.
- `--facility` is repeatable. Source execution is dataset-first, with one facility checkpoint per date-based dataset. The registered scenario owns organization `aspire-demo` and scenario key `aspire-demo`; different values fail rather than being ignored.
- `--from` applies to scoped rebuilds, backfills and reporting refreshes. Normal update/populate find every missing date in retained history. A requested repair before retained history fails; it does not invent or trim earlier data.
- Completed zero-activity dates are recorded. Existing dates outside the rolling display window remain retained on ordinary operations.
- A stateful repair starts from the last compatible boundary before the first affected day and continues through the retained end so later census remains consistent. Only the selected facility is replayed. Plans explain this expansion.
- `--entity` supports payer reference codes and the hospital-assignment admission IDs described above. Unresolved generic resident/stay/bed entity scopes fail explicitly.
- `--generator-version DATASET=VERSION` pins a registered version. It does not dynamically load arbitrary generator code.
- `--batch-size` bounds insertion batches (1-10000). `--concurrency` currently accepts 1 because publication and source ownership locks serialize this runner's writes.
- Bare `rebuild` is rejected: specify a dataset. `full-reset` is a separate explicit operation for the scenario-owned population. It does not erase arbitrary database tables or imported/manual populations.

## Existing data, daily catch-up and recovery

Legacy global completion records can be adopted into per-facility coverage without recreating admission rows. Existing active stays provide an initial boundary when they reconcile with recorded census. Thereafter, movement checkpoints retain the active queue and reusable discharged residents. Ordinary daily catch-up continues from a compatible boundary instead of replaying from the historical simulation anchor.

New admissions use independent deterministic randomness for volume, demographics, payer assignment and source assignment. New readmissions reuse a known previously discharged resident identity and record the actual gap. Historical resident identities are preserved; old source readmission flags are not treated as proof that differently identified people should be merged.

Coverage transitions preserve already-recorded payer intervals and continue affected stays. Reference aliases keep renamed payer displays attached to the same plan IDs. A newly published day with no payer events still advances coverage/readiness.

New runs finish each source dataset across the selected facilities before starting the next dataset. Each dataset/facility batch commits its source changes and checkpoint. Resident planning resolves readmissions without writing admissions. Residents are committed first, then canonical census stays, admission/discharge compatibility records, and canonical payer intervals before payer-change compatibility records. Reporting then groups affected facilities by date interval and commits summaries/publication separately. A reporting failure does not roll back or regenerate completed sources. Resume skips completed stages. Existing version-1 and version-2 runs retain their recorded execution paths for recovery only; new runs record pipeline version 3. No background schedule is created.

## Two-stage execution (schema migration 7)

Run schema upgrades explicitly before using the new runner. No full reseed is required to adopt this code.

```sh
# Source loading followed by reporting, in one command:
python -m seeding populate --through today
# Only source loading (the output supplies the load ID):
python -m seeding populate --through today --sources-only
# Only reporting for that completed source load; no fake generation:
python -m reporting --load-id LOAD_ID
# Recover an interrupted combined/source run:
python -m seeding resume --run-id RUN_ID
```

In Docker development use `docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml run --rm --no-deps seed ...` for seed commands and the `reporting` service for report commands. Keep the database running. Use the same file combination with `migrate upgrade` to apply migrations through version 7 after the old run finishes, not during it.

Source stages (across all selected facilities before moving to the next stage):

1. States, portfolios, regions, facilities/hierarchy assignments, hospitals, and payer references, in that order.
2. Resident identities. Plan missing arrivals and resolve readmissions in memory; persist residents and the durable scenario plan together. No admission or stay is written during planning.
3. Shared census stays, referencing residents that already exist.
4. Admission records, then discharge/stay compatibility records and movement checkpoints, from the saved plan. There is no second movement simulation.
5. Shared payer stays before their compatibility periods/change records, then bed-hold snapshots.
6. Reporting summaries and publication in the separate reporting phase.

`registry.source_stages` supplies both preview and execution dependency ordering. The resident generator retains existing deterministic keys; this is a write-order correction, not a new population scenario. Admission/readmission relationships are resolved before persistence. The `seed_source_plans` table (migration 6) holds one bounded facility plan at a time per stage and is cleared per facility when its movement stage commits. A failed stage retains its plan; progress metadata stays small. Existing incomplete runs continue through their older recovery path.

Daily movement counts inside scenario planning are working inputs for reconciliation and bed holds; published report summaries are rebuilt only afterward. Compatibility event tables remain current API read models. This change does not remove those tables or convert all report queries to canonical-only reads. Named historical backfills deliberately retain the legacy conversion adapter. A payer-only update checks shared stay prerequisites and does not create admissions or residents as a side effect.


A pending load blocks ordinary source loading for that organization. Resume it to retain its progress. An explicit `full-reset` can instead supersede a failed demo run whose scope it fully covers; active runs are never taken over. The old run stays in the audit history as superseded and cannot be resumed or published. Replacement registration and supersession commit together, so reporting remains unavailable until the replacement finishes. `--sources-only` deliberately leaves reporting pending; complete it with `reporting --load-id`. Console progress shows one start and one completion message per dataset, with its total duration; individual facility timings remain in checkpoint metadata. Failures still identify the specific facility batch. Reporting definitions still come from the existing report dependency registry; this runner does not add unimplemented state/region/portfolio summaries or claim that every API is already optimized. No source or reporting operation is run on application startup.

## Current limitations

### Population performance target

The requested target for the current 253-facility demo, including 36 complete months plus the current month and its reporting summaries, is a full population targeting two to three minutes. This is a target, not a measured result or a guarantee for arbitrary hardware or future datasets.

The shared database writer is `data/writers/core.py`. Admissions, stays, discharges, census, payer periods/changes, bed holds, facility/hospital references and daily completion records use it; canonical synchronization and report projections use its compatible `upsert_rows` entrypoint. It owns bounded batches, PostgreSQL parameter limits, changed-only writes, conflict handling, JSON adaptation and returning inserted IDs. Large merges use COPY into a temporary staging table followed by a set-based insert/update; direct new-row loads use COPY. Small writes and inserts requiring SQLAlchemy client defaults use SQLAlchemy. Temporary staging tables are transaction-local and do not alter the persistent schema. No writer commits independently.

Admission rows accumulate across days. Discharge/readmission identity corrections are bulk updates, not one statement per resident. Hospital directory/profile lookups are cached by their stable scenario inputs; readmission matching uses resident-ID sets instead of repeatedly scanning the active queue. Per-facility label publication only scans that facility; explicit payer-reference renames still publish across the organization. Global reporting completeness skips its full date scan while any facility still lacks coverage. Generated identities, history, validation and transaction boundaries are preserved by these changes; runtime equivalence has not been measured.

New executions print one completion line per facility with its elapsed time, only after its transaction commits. Detailed per-generator, canonical synchronization and reporting timings remain saved in batch details rather than printed. Resume reports skipped completed batches. These code changes do not change a process that has already loaded the old code. No seed, database operation or performance measurement was run to apply this optimization.

- The registered synthetic population is the current facility scenario, with a movement simulation anchor of January 2020. A 36-month window that begins before that anchor is rejected. Additional scenarios require registered definitions and versions.
- Changing the capacity of an already populated facility is not supported as a normal reference-field update. It fails rather than silently recreating residents. A coordinated capacity repair needs a separately implemented scenario operation; full reset remains an explicit exceptional choice.
- Payer and plan display-name edits are supported with `--changed-field name`. `--changed-field type_name` is rejected because the current HTTP/UI payer-type vocabulary has not yet moved to canonical display names; this version does not claim complete payer-type label propagation.
- Legacy source rows did not record every real-world fact or provenance distinction. The adapter preserves known identities and flags; it does not invent historical bed assignments, absences or resident merges.
- Facilities containing canonical imported/manual stays or payer intervals are protected from fake generation. An explicitly demo-marked database does not override source ownership.
- Source batches commit separately from reporting. The current API uses an explicit unavailable state while a source load/report publication is pending; it does not yet retain historical serving snapshots. The compatibility API is globally gated, even though loads are organization-scoped.
- A first population/rebuild may replay the anchor for the selected facility. New daily updates use checkpoints. No throughput or latency claim has been measured for this refactor.

These are implementation gaps/status observations, not lasting prohibitions in the architecture instructions.


### Location references (migration 7)

`states(state_code, name)` is shared geography; `facilities.state` has a foreign key to it. Migration 7 installs US state/territory references and preserves any other existing facility state codes using the code as the initial label. It does not regenerate facilities or residents. Portfolios and regions retain their existing IDs and tables; facility hierarchy periods link facilities to both. No state foreign key is imposed on a portfolio or region, so organizational scope can span states. Existing demo codes retain their historical prefixes as stable identifiers.

New default population/reset runs seed states, portfolios and regions before facilities. Each reference dataset can also be selected independently; missing prerequisites produce an error rather than triggering an implicit population rebuild. Facility-only updates require those references to exist. The reverse reference adapter remains for explicit historical adoption and older run recovery, while new facility stages only write assignments to pre-existing parents.
