# Shared database workflow

`shared/database/schema.py` is the relational schema for the seeder and future API.
The seeder retains generator-specific logic in `sandbox-data`; its base class aliases
the shared table objects. The FastAPI foundation also imports these objects; its
structure and startup commands are in [backend-structure.md](backend-structure.md).

The structural reference and relationship diagram are generated in
[database-schema.md](database-schema.md). Keep column meanings in `Column.info`
and table descriptions in `Table.info` beside the schema. These descriptions do
not alter database DDL.

## Setup and normal use

Use Python 3.11 or newer. From `sandbox-data`:

```powershell
python -m pip install -r requirements.txt
python manage.py status
python manage.py update
```

`upgrade` creates/migrates the schema and runs applicable historical backfills.
`update` first publishes a changed schema draft, applies migrations and required
backfills, then seeds/catches up missing simulation days through today. If schema
work fails or pauses, daily generation does not start. Neither command rerolls
completed days. A new database can be initialized with `update`. Reference generators retain their existing skip
behavior. `migrate` applies schema changes only; it stops if a revision requires
an unfinished backfill. Use `update` for normal use; `upgrade` remains available
when only database preparation is wanted.

All commands read the repository root `.env` / `DATABASE_URL`. `--plan` describes
code-defined order without connecting. `status` reads actual database history.
The package can also be installed from the repository root using
`python -m pip install -e .` so another Python entry point can import
`shared.database.schema` without changing import paths.

## Existing databases

The first Alembic revision adopts the supported sandbox schema. It validates and
preserves the two original SQL migration checksums, applies either legacy change
if still pending, checks existing tables, and creates missing tables. It does not
regenerate reference records, residents, stays, logs or summaries. The old SQL
files now live under `shared/database/migrations/legacy` and are immutable.

Adoption checks Alembic-comparable structure and primary keys; incompatible
structure aborts and rolls back the adoption transaction. It never blindly stamps
an arbitrary database. CHECK expressions still require review: Alembic does not
reliably compare every database constraint. Unrelated tables are left alone.

Adopting schema history does not convert the old future-dated ADT simulation into
daily simulation state. If a database still contains legacy fixed-window ADT with
no daily checkpoints, `seed`/`update` retains the existing explicit reset message.
`seed --reset-history` drops every table this package owns, migrates back to head
and rebuilds everything, including reference data and residents; it is not part of
normal upgrades. Dropping is O(1) per table where deleting rewrites every row and
leaves the dead ones behind, and nothing is lost: the same seed and saved facility
list reproduce the same IDs and the same data.

## Change a column or table

1. Run `python manage.py stage`. This creates `shared/database/staged/schema.py`
   from the current active schema, plus a draft backfill registry and base manifest.
2. Edit **the staged schema**, leaving active `shared/database/schema.py` alone.
   Against a development database at the previous migration head, run
   `python manage.py revision --message "describe the change"`.
3. Review the generated file in `shared/database/staged/migrations/versions`.
   Autogeneration produces a draft, not a guaranteed safe migration. A rename
   commonly appears as add/drop and must be rewritten as a rename. Review casts,
   defaults, nullability, constraints and indexes. Removing an entire table from
   metadata is deliberately not auto-dropped because reflected unrelated tables
   are excluded; write an explicit reviewed drop when intended.
4. For a large data rewrite, add a new job in `staged/backfills` and register it in
   `staged/backfills/runner.py`. Keep applied jobs/migrations unchanged.
5. Run `python manage.py update` when ready. It publishes the reviewed files,
   upgrades the schema/backfills, regenerates schema documentation, and catches up
   missing days using a fresh process that imports the published schema.
6. `python manage.py check` inspects the active database/schema/documentation.
   Commit the promoted schema, new migration/backfills, and generated docs together.

Drafts are excluded from API migration discovery and development reload watching.
Restart an already-running development launcher once after installing this staging
workflow so its supervisor loads the new directory exclusions. After that, editing
a draft does not reload the API. Ordinary `upgrade` ignores drafts;
`upgrade --staged` explicitly applies one without generating missing days.

`status` and `update --plan` show staged changes without applying them. Creating
or editing a draft does not require stopping the API. Application is the explicit
update boundary: migrations/backfills may temporarily cause 503 responses under
the existing database lifecycle lock. With `serve --reload`, a final reload is
requested after success. A non-reloading server still needs a restart to import
the new schema. Renamed/removed columns still require corresponding backend changes.

A draft records its active base and rejects conflicting active edits. Review one
autogenerated migration per draft; further migration steps may be authored as a
single ordered chain. On application, content is frozen by checksum. A failed or
batch-limited update resumes with `update` using that exact content; do not edit
an applying migration. Earlier committed migrations/batches remain committed.
The next `stage` archives a completed draft under ignored `stage-history/` and
starts from the new active schema. Staged source files may be versioned for review;
an applying draft's manifest is also required to resume interrupted publication.

Each revision commits independently and records a checksum of its source and
declared artifacts. If a later revision fails, earlier committed revisions remain
applied. Restore a modified applied file and add a new corrective revision. Never
edit applied files, delete history records, or manually stamp past missing work.
The frozen baseline snapshot is historical migration code, not another schema to
maintain. New revisions must not import the mutable live schema to define old DDL.

`check` verifies the current head, immutable migration/backfill history, required
backfill completion, detectable schema drift, primary keys, and generated docs.
It does not prove business logic correctness or eliminate human error. It ignores
tables not owned by this package and cannot reliably detect all CHECK, trigger,
function or extension changes. Such changes need explicit migration review.
`schema-docs --check-docs` checks documentation without connecting to a database.
Neither check applies changes; neither is a test suite.

## Historical backfills

Add a versioned Python file under `shared/database/backfills` and register it in
`JOBS` in `runner.py`. The runner orders jobs by `depends_on`, not filenames.
Use the existing `discharge_payer_los_v1.py` as the concrete example. It corrects
discharge LOS to the final payer period without rebuilding ADT or changing IDs.

A job declares:

```python
name = '0002_example'
depends_on = ('0001_discharge_payer_los',)
required_revision = 'revision_that_adds_the_needed_columns'
required_tables = ('table_with_historical_rows',)

def ready(connection):
    # Optional: return a reason string to defer, or None when source data is ready.
    return None

def run_batch(connection, checkpoint, batch_size):
    # Read a bounded batch using an indexed, stable key and a saved upper boundary.
    # Write idempotent updates using only this connection. Never commit here.
    # Return a JSON-serializable checkpoint, rows checked, rows changed, complete.
    ...
```

The runner commits each batch with its checkpoint. On failure the current batch
rolls back, and rerunning `upgrade` resumes after the last committed batch. Jobs
cannot open independent transactions, commit themselves, or depend on mutable
generator rules. Put immutable SQL/rules inside the job file so its checksum
covers the transformation. A correction is a new job ID with a dependency on the
old job. Completed jobs remain in source control.

Use keyset pagination rather than OFFSET and bound large scans/updates. The sample
job saves a UUID upper boundary, scans indexed IDs and only changes incorrect LOS.
It fails on missing/inconsistent final payer periods rather than marking incorrect
data complete. New generator rows already use the current LOS rule. Correcting
LOS does not affect admission summaries; changes to metrics used by summaries
must explicitly rebuild/invalidate those summaries in their own dependent job.

Missing schema revisions, tables, source readiness or dependent jobs defer work;
they are never silently counted as complete. Empty source tables can legitimately
complete a historical correction if future generators already emit the right data.
Use `ready` when emptiness means prerequisites have not yet been seeded. Avoid a
cycle where a prerequisite is blocked by the very backfill waiting for it: prerequisite
data must be created by an earlier upgrade job, or seeded before introducing that
requirement. Declare any required data insertion as an earlier backfill.

To stop after a bounded amount of committed work:

```powershell
python manage.py upgrade --batch-size 10000 --max-batches 20
python manage.py status
python manage.py upgrade
```

If required work remains, the bounded command exits nonzero and says to resume.
An interrupted run may show `running`; that means a saved checkpoint exists, not
that another process is necessarily still executing. The terminal uses one live
progress line with counts and ETA when a total is known, then a short result for
each completed task. Backfill counts update after each committed batch. Redirected
logs contain final results and progress snapshots every 30 seconds, without cursor
control characters. Use `--plan` for detailed run order and `status` for saved history.

For adding a required column to a large table, use expand/backfill/contract:
first add it nullable, backfill it, then add NOT NULL in a later revision. On the
later revision set `required_backfills = ('your_backfill_id',)`. `upgrade` completes
those jobs before applying that revision, including when both revisions arrive in
one pull. The job's `required_revision` must point to the earlier expansion, never
the later constraint revision. Prerequisite jobs must work at the schema version
where they are scheduled. Schema-only `migrate` stops at unfinished data prerequisites.

## Payer/reference changes

For a local demo-only payer addition, edit `sandbox-data/hard_coded_data/payers.json`
and run `python manage.py payers --regenerate` after upgrading. The existing
generator upserts the catalog and retains saved parent IDs. A new payer does not
automatically rewrite existing payer stays; subsequent simulation can select it.

For a change every checkout must receive through `upgrade`, include a versioned
idempotent reference-data backfill with a fixed copy of the new values. Resolve
existing keys from the database; do not reconstruct existing parent IDs. Also
update the source JSON/current generator for newly seeded databases. Historical
reassignment is a separate explicit backfill if wanted.

## Demo distribution changes

Payer-type and admission-source weights vary by facility, month, and day. Stable
facility preferences combine with shared calendar changes so the group-wide mix
also moves over time. Source baselines are roughly half Hospital, with unequal
non-hospital shares; they are probabilities rather than exact quotas. Hospital
names still come from the saved region's scored hospital list. Skilled eligibility,
100-day limits, and the roughly 50% State Medicaid selection rule still apply.

Medicaid census targets vary by facility around 55–75%, with monthly movement
bounded within 50–80%. New-admission payer probabilities respond to the current
Medicaid census, and initial Medicaid admissions have longer planned stays
(90–730 days). Opening residents include time already spent in the facility.
This is a probabilistic census target, not a guarantee for every facility/day;
existing plans, payer changes, discharges, and small counts can cause excursions.
It does not require 50–80% of new admissions to use Medicaid.

Profiles are deterministic from saved IDs, dates, and the generator seed, with
bounded in-memory caches. Running missing dates together or separately uses the
same rules. Existing active stays retain their already-saved payer plans.

Generator rule changes apply to newly simulated admissions. `update` does not
rewrite completed history, and regenerating a summary does not reroll its source
data. To deliberately replace the demo history with the revised distributions,
run `python manage.py seed --reset-history` from `sandbox-data`. This drops and
rebuilds every owned table, so reference data and residents are regenerated too.

## Medicaid Pending lifecycle

`Medicaid Pending` is a non-skilled payer in the `medicaid` category. It is excluded
from ordinary approved-payer selection and later payer-change destinations.
Roughly half of admissions whose initial payer type is Medicaid start pending,
with a deterministic approval delay of 7–14 days. Both pending and approved
Medicaid count toward the facility's Medicaid census target.

While unresolved, the first payer period and admission log use Medicaid Pending.
On the approval day the daily handler updates that **same** payer period and the
admission log to the approved payer, effective from the original admission date.
It also updates the private active plan. Approval is a retroactive correction,
not a payer-change event: no extra period, payer-change count, or LOS reset.
The first period lasts through approval before any ordinary payer change.
Opening residents whose approvals predate the first simulation day are already
assigned their approved payer.

`medicaid_applications` retains one row per pending-at-admission case, with the
application date and actual approval date/payer. Unresolved approvals have null
approval fields. Future intentions are stored only in
`sandbox_adt_active_stays.medicaid_approval`. Plans and actual changes commit with
the same daily checkpoint, so missing-day catch-up also processes approvals.

Reporting meanings:

- Pending admissions received: count application rows by `application_date`.
- Currently unresolved: application rows with `approved_date IS NULL`; join open
  stays when the metric is specifically residents still in the building.
- Pending as of an earlier day: `application_date <= day` and approval null or
  `approved_date > day`.
- Approval duration: `approved_date - application_date`.

Daily admission facts and API metrics include the additive
`medicaid_pending_admissions` count, which remains after approval. Log API rows
include `started_medicaid_pending` and `medicaid_approved_date`. Regular payer
fields show the corrected payer. Facts keep `payer_id` at the grain and reports
group it to a payer type, so a pending-to-approved Medicaid correction changes
neither payer-type totals nor previously built dates. The count is derived from
`medicaid_applications` whenever facts are built, so a rebuild reports it
consistently across history rather than defaulting older dates to zero; dates
with no application rows are genuinely zero.

Run `upgrade` for revision `0002_medicaid_applications`, then
`payers --regenerate` to sync the catalog. Existing history is not assigned
invented application records by the migration. New admissions use the new logic;
an intentional `seed --reset-history` rebuild includes it throughout demo history.

## Rebuilding derived tables on their own

Admission and discharge logs are derived: their referral source, destination and
deceased flag come from the stay ID through the same seed the simulation uses, and
their readmission flags and payer come from saved stays and payer periods. Rebuild
either without touching the simulation:

```powershell
python manage.py admission_logs --regenerate
python manage.py discharge_logs --regenerate
```

Use this after changing source weights, hospital scores or a log column, instead of
replaying history. Payer periods are not separable this way: the payer type chosen
at admission decides the planned length of stay, which decides the discharge date
and therefore later admissions, so changing payer rules genuinely changes history
and needs `seed --reset-history`.

## Bulk admission facts

From `sandbox-data`, rebuild saved admission facts with:

```powershell
python manage.py admissions_summary --regenerate
```

Use `--from YYYY-MM-DD --through YYYY-MM-DD` to rebuild a selected range, or
`--date YYYY-MM-DD` for one date. Completed ADT days are reused; missing ADT
dependencies are generated first. Ordinary `update` only builds missing dates.

`daily_admission_facts` holds one row per (date, facility, payer, referral source)
that had admissions, with additive measures. Reports group those rows, so parent
location totals are query results rather than stored copies, and no row is written
for a scope-day with no activity. Absence means zero; completeness comes from the
date checkpoints. Keeping the payer and source name at the grain means new
breakdowns over existing dimensions need no regeneration, and a new additive
measure is a column plus a backfill rather than a rewrite of every stored object.

The builder runs one `INSERT ... SELECT` over the selected admissions. There is no
per-scope query, per-day query, or Python aggregation loop.

Selected dates and their checkpoints publish in one transaction. Existing facts
remain readable until commit; failure rolls back the entire batch, including its
checkpoints. Rebuilds therefore restart the batch after failure rather than
resuming individual dates. ADT remains resumable by day. The daily runner
processes handlers in dependency order; derived handlers can opt into `bulk_dates`
and implement `run_dates` without forcing the simulation itself into a bulk query.

## API readiness and versions

Import the shared tables directly. Call
`shared.database.lifecycle.ensure_compatible(connection)` before serving data;
it checks schema history and required backfills but never runs long work at API
startup. A feature can supply `required_backfills=(...)` for its own readiness
requirements. The default requires all registered jobs; unknown IDs fail closed.
Schema heads must match this checkout exactly, including when old code connects to
a newer database. The backend runs the full guard at startup and on `/api/v1/ready`,
and checks the schema head in each reporting database dependency.

Schema revisions, data-backfill IDs and daily simulation checkpoints are separate
histories. Derived reporting tables such as `daily_admission_facts` follow the
ordinary migration and backfill path: adding a measure is a nullable column, a
backfill, then a NOT NULL revision, and changing the grain is a migration plus a
regeneration of the affected dates.

Upgrades take an exclusive lifecycle advisory lock. Generator runs take the shared
side so schema/data upgrades cannot race cooperating seeder commands. The daily
runner retains its own lock to serialize dates. API reads take the shared lifecycle
lock before their snapshot; future API writers must also cooperate with that
protocol. Arbitrary SQL clients are not protected by it.
This first implementation pauses seeding during an upgrade. Online rolling schema
deployments and unrelated simultaneous writers are not implemented.
