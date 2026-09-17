# Backend refactor implementation and rollout

Code inventory: September 17, 2026. This describes the prepared implementation, not the state of a running database. Durable rules remain in [instructions.md](../instructions.md). No migration, seeder, backfill, service, or database inspection was run while preparing this refactor. No tests were written, changed, or run.

## Package boundaries

| Package | Implemented responsibility |
| --- | --- |
| `backend/api` | Existing HTTP routes and response contracts, services, read queries, request error handling. Requests use a consistent read-only database snapshot. |
| `backend/data` | Shared models, lazy database setup, explicit migrations, source writers, organization/source ownership checks. |
| `backend/domain` | Stable identity helpers and shared business definitions. |
| `backend/reporting` | Event projections, daily/monthly summaries, hospital performance, dependency planning, coverage, cache revisions and publication. |
| `backend/seeding` | Demo reference definitions, independent generators, planning, facility batches, catch-up, backfills and durable resume state. |
| `backend/common` | Configuration and the explicit reporting clock/timezone. |
| `backend/app` | Compatibility imports and old command entrypoints. New implementation belongs in the packages above. |

API and reporting code do not import fake generators. Reporting has its own registry, planner and command, so ingestion can publish results without loading the seeder. Schema changes belong to versioned migrations; importing packages, serving requests and running a generator do not apply DDL.

The frontend was not changed. Existing API paths and response shapes remain the serving contract. Missing schema/publication coverage produces an actionable unavailable response; an admission range outside published coverage is rejected rather than represented as zero activity.

## Shared source model

Migration 4 adds shared organizations, residents and source identifiers; census stays; payer types, payers, plans and payer intervals; external locations and assignments; facility hierarchy/capacity history; rooms, beds, assignments, absences, reservations and statuses. Relationships use stable IDs and organization-scoped foreign keys. Demo and production use these same migrations and model definitions.

Existing `adt_*` tables remain compatibility projections and serving aggregates. Removing them would break active reports and is not part of the package transition. The two explicit adapters are:

- `data.writers.legacy.sync_sources`: adopt existing generator-owned history into shared entities, preserving its IDs. This is used by the named adoption backfill and changed demo batches.
- `reporting.projections.canonical.publish_legacy_read_models`: publish canonical ingestion facts to the existing serving contract. It never imports compatibility rows back into canonical sources.

The current generators still produce their established ADT records before synchronizing shared sources within the same transaction. This preserves existing scenario identities and behavior. It is a transition adapter, not a claim that every generator already writes only normalized tables.

Unknown historic facts are not invented during adoption. Legacy resident names do not prove two IDs are one person. Current hierarchy/capacity observations do not establish earlier effective dates. Existing aggregate bed holds do not establish individual bed assignments or absences. Those canonical tables are available for explicit source data; adoption does not fabricate their contents.

## Source writes and reporting publication

`data.writers.source.write_source_batch` accepts a caller-owned transaction, an organization, explicit facility IDs and rows keyed by shared table name. It writes in dependency order, checks ownership and validates interval relationships. Call `reporting.runner.refresh_from_canonical` with the affected scope in that same transaction to publish compatible report projections and summaries.

The report registry declares source and field dependencies. A correction can refresh affected reports without generating people. Monthly computations reread affected whole months; a stay correction can propagate through later retained dates. The caller must supply the full affected interval for a historical correction. Corrections that change older event identity or membership require an expanded projection scope rather than silently rewriting events outside it.

Coverage is stored per report, facility and date, including known quiet days. Data, coverage and revision changes commit together. API readers use committed snapshots. Existing global readiness fields are maintained from the common complete coverage across facilities; they remain a compatibility limit, not per-organization publication versions.

New seed runs use dataset-first source checkpoints followed by a separate grouped reporting phase. Migration 5 adds a shared source-load journal and facility reporting indexes. The API explicitly reports unavailable during an incomplete load; no historical serving snapshots or background worker are introduced. Version-1 seed runs retain the legacy runner for recovery. See backend/seeding/README.md for source-only and reporting-only commands.

## Explicit database rollout

Package separation alone does not require regenerating existing people. The prepared schema version is **5** (source-load publication tracking and facility reporting indexes). Databases must receive that migration before using the new schema-dependent paths.

The following are commands for an operator to review; they were not executed. From `backend`, using the backend Python environment:

```powershell
python -m data.migrations upgrade --preview
```

Migration 4 creates the new source/operation/coverage tables, adds nullable facility organization ownership, carries forward supported legacy publication coverage and updates invalidation triggers. It does not assign every existing record an organization, generate history or mark a database as demo. Applying it is an explicit operation, separate from preview.

For demo generation, set `ENVIRONMENT=development` or `demo` and a local `DEMO_INSTANCE_ID`. The explicit `data.migrations configure-demo --instance-id ...` operation records that instance and the actual database name. Generator commands require the configuration and database identity to agree; setting an environment variable alone does not authorize an unregistered database.

Existing legacy histories can be adopted without a full reset. From the repository root, first review:

```powershell
python seed_data.py backfill --backfill-name canonical_sources --preview
python seed_data.py update --through today --preview
```

Use `--facility` to narrow either operation. The adoption backfill preserves known identities; update fills missing dates and reconciles dependent data. Neither command applies schema migrations. See [the seeding reference](../backend/seeding/README.md) for execution flags, supported narrow scopes and recovery.

An independent reporting plan, from `backend`, looks like:

```powershell
python -m reporting --dataset referring_hospitals --from 2023-09-01 --through 2026-09-17 --preview
```

Use the actual retained dates for the requested report. Canonical ingestion publication additionally requires `--from-canonical`, `--organization` and explicit `--facility` values; it refreshes affected dependencies together. Normal reporting refresh only reads existing facts.

## Implemented seed behavior

- Offline preview is separate from explicit read-only inspection.
- Populate/update, scoped rebuild, named backfill, reporting refresh, resume and full reset are separate commands.
- All date-based generation retains 36 complete months plus the current month to date; ordinary updates preserve older existing history.
- Completed zero-activity dates are recorded. A missed run is caught up on the next explicit update.
- Stable identities and independently keyed generation attributes keep reference additions from renaming unrelated residents or changing admission dates.
- Reference labels update separately from historical assignment. Adding a payer does not redistribute old coverage.
- Stateful generation keeps compatible boundaries and per-facility completion records. Work and its checkpoint commit together.
- Dataset dependencies are explicit; requesting a dependent dataset does not silently regenerate every ancestor.
- Demo targeting and source ownership are checked before writes. Unsupported scopes fail with a reason.

## Remaining transition limits

These are implementation observations, not permanent restrictions on future work:

- Existing query algorithms and optimized hospital summaries were preserved. This refactor does not mean every report is now precomputed, or that latency has been measured. Prototypes can continue to be optimized individually.
- The existing API/read-model contract is still oriented to the current shared deployment. Organization-aware canonical writes are not a replacement for implementing tenant-aware authorization and organization-scoped HTTP reporting when requested.
- The legacy event contract supports its current payer/source categories, field sizes and date-level semantics. Canonical publication rejects unsupported categories, unknown required admission/LOS facts and timestamp-precision histories it cannot faithfully represent; it does not silently discard precision. Broader production inputs require an explicit serving-contract extension.
- Bed-level canonical histories are defined, but current live-census bed-hold counts still use the established daily snapshot path. No individual bed-history generator was inferred from aggregate counts.
- The demo runner currently registers one scenario/organization and uses concurrency 1. Narrow entity selection exists for named operations, not arbitrary edits to every entity type. Populated-facility capacity changes need an explicit scenario repair; the normal reference command refuses to recreate the population.
- The shared writer uses bounded upserts, with per-record ownership lookups. Large production ingestion throughput still needs measurement and, where warranted, bulk validation improvements.
- No automatic daily scheduler was created. Update and resume are explicit terminal-owned commands.

## Review performed

Read-only source review covered package dependencies, schema/model references, transaction ownership, scoped deletion/update paths, CLI planning and launcher changes. Python files were syntax-parsed without importing application code. Runtime behavior and performance remain unverified because no services, database operations or tests were run.


## Resident-first source loading ? 2026-09-17

New pipeline-version-3 runs now resolve readmission identity in a read-only scenario plan, persist shared residents, then shared census stays, then admission/discharge compatibility records. Coverage writes shared payer stays before compatibility periods/events. Source planning is durable in `seed_source_plans` (migration 6), consumed without re-simulation and cleared on committed movement persistence. Reporting remains the separate second phase. Normal new loads no longer call the reverse `sync_sources` bridge; explicit historical backfills and saved older runs retain it.

This supersedes earlier descriptions of normal loads creating residents after admissions. Migration 6 is prepared, not applied. No database operations, seeding, runtime benchmarks, or tests were executed for this correction. Existing source IDs and simulation rules were preserved. Compatibility tables remain in use by current APIs.


## Location reference order ? 2026-09-17

Migration 7 adds shared states and the facility-state foreign key without replacing existing data. Separate state, portfolio and region seed stages now precede facilities. Existing portfolio/region IDs and facility hierarchy periods are retained. Geography does not constrain portfolios to a single state. Migration and generators are prepared only; no migration, seed or tests were run for this change.
