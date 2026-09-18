# Project instructions

## Start here

[README.md](README.md) explains what this is and how to run it.
[docs/overview.md](docs/overview.md) explains why it exists, and is worth reading
before changing anything structural.

| Question | Document |
| --- | --- |
| Why does this demo exist, what is it for | [docs/overview.md](docs/overview.md) |
| How is the API built, how do I add a report | [docs/backend-structure.md](docs/backend-structure.md) |
| How is the data generated, what tunes what | [docs/generators.md](docs/generators.md) |
| How do I change the schema | [docs/database-workflow.md](docs/database-workflow.md) |
| What do the tables contain | [docs/database-schema.md](docs/database-schema.md) |
| What was measured, what breaks at scale | [docs/scaling.md](docs/scaling.md) |
| How do containers and snapshots work | [docs/docker.md](docs/docker.md) |
| What is next, what is knowingly unfinished | [docs/roadmap.md](docs/roadmap.md) |
| Frontend components and patterns | [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md) |

## Scope and changing priorities

- The user's current request determines which module or report to build and which
  existing behaviour to change. There is no prescribed module order.
- Dated plans, audits, schema proposals and UI snapshots are context, not permanent
  restrictions or prerequisite checklists. Verify their claims against current code.
- Do not ask for reconfirmation merely because a clear new request differs from an
  older plan or UI choice. Preserve unrelated behaviour and implement the requested
  scope and its actual technical dependencies.
- Keep durable rules separate from report contracts, demo scenario choices,
  implementation status and proposals. Do not convert a current limitation,
  temporary UI experiment or existing module list into a restriction on future work.

## Tests

- Do not write, add, modify or run tests unless the user explicitly requests it.
- Do not run test suites automatically after implementation or bug fixes.
- The user will report broken behaviour and decide when tests are needed.
- Complete requested changes without spending time or tokens on unsolicited tests.

## Frontend and UI

- Before changing UI, read [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md),
  including its shared interaction patterns and component map. Report-specific
  historical choices live in [docs/ui-context.md](docs/ui-context.md).
- Reuse shared components and tokens. Fix shared behaviour in its owning component
  rather than creating report-specific copies or CSS workarounds.
- Preserve UI choices outside the requested change; verify dated implementation
  descriptions against code. The no-tests rule above also applies to frontend work.

## Architecture invariants

Breaking one of these is a design change, not a refactor. Each was measured; see
[docs/scaling.md](docs/scaling.md).

- **Reporting tables are facts at event grain**, one row per event with additive
  measures. Not one pre-aggregated document per scope per day. That design was
  12× larger, 8.5× slower to rebuild and slower to read.
- **Parent scopes are `GROUP BY` results, never stored.** Storing group, state,
  portfolio and region rows alongside facility rows invites double counting and
  buys nothing.
- **Absence of a row means zero. Completeness comes from `sandbox_daily_runs`
  checkpoints.** A generated day with no admissions has no fact rows and must read
  as zero; a day never generated must return 409. Do not use row presence for both.
- **One fact table per event type, not per report.** Six ADT reports derive from
  four event sources. Referring Hospital needs no new table — `source_name` is
  already at the grain.
- **Keep dimension keys at the grain** (`payer_id`, not `payer_type`). The finer
  grain measured as free and makes future breakdowns possible without regenerating.
- **Sum numerators, divide once.** Never average a column of averages. Store
  `sum_los` and a count as separate columns, never a pre-computed mean, or every
  roll-up above facility level is silently wrong.
- **Services never call another endpoint over HTTP.** They take a connection and
  explicit selections.
- **Location selection is not authorisation.** It narrows data. There is no
  authentication in this demo.

## What a change actually costs

Check this before editing a generator. Full detail in
[docs/generators.md](docs/generators.md).

| Change | Rebuild |
| --- | --- |
| Metric derivable from existing fact dimensions | **Nothing** |
| Referral sources, hospital scores, discharge destinations | `admission_logs --regenerate`, seconds |
| New additive measure on a fact table | Column, backfill, `admissions_summary --regenerate` |
| **Any payer rule, stay length or census target** | **Full `seed --reset-history`, ~9.5 min** |

The last row is circular and unavoidable: payer decides length of stay, which decides
discharge date, which decides census, which decides tomorrow's admissions. You cannot
hold `res_stays` fixed and regenerate payer periods over it.

## Commands

From `sandbox-data` unless noted. Full list in [docs/generators.md](docs/generators.md).

```powershell
python manage.py update                         # migrate, then generate missing days
python manage.py seed --reset-history           # drop everything, rebuild from 2023-01-01
python manage.py status                         # migrations, backfills, staged drafts
python manage.py admissions_summary --regenerate
python manage.py admission_logs --regenerate    # rebuild one table from saved stays
python backend/manage.py serve --reload         # from the repository root
docker compose --env-file .env.docker up --build
```

## Traps that have already cost time

- **`postgresql+psycopg://` is a SQLAlchemy URL.** `pg_dump`, `psql` and every other
  libpq tool need `+psycopg` removed. Passing it whole makes `pg_dump` hang without
  connecting and without an error.
- **Settings need the `API_` prefix.** `API_CORS_ORIGINS`, `API_TIMEZONE` and so on.
  `DATABASE_URL` is aliased and does not. A bare `CORS_ORIGINS` in `.env` is silently
  ignored — and currently is.
- **`API_CORS_ORIGINS` is parsed as JSON**, so it needs a JSON array, not a
  comma-separated list.
- **PostgreSQL 18 moved its data directory.** Volumes mount `/var/lib/postgresql`,
  not `/var/lib/postgresql/data`.
- **A database healthcheck must probe TCP** (`pg_isready -h 127.0.0.1`). While the
  entrypoint restores anything in `docker-entrypoint-initdb.d` it runs a temporary
  server with `listen_addresses` empty, so a socket probe reports healthy and
  dependants start against a half-restored database.
- **Alembic autogenerate writes neither CHECK constraints nor table drops.** Both
  must be added by hand, and a `nullable=False` column added to a populated table
  fails without a default. Always read the generated migration.
- **Schema edits go in `shared/database/staged/schema.py`**, never the active file.
  `manage.py stage` creates the draft; `update` publishes it.
- **VS Code's git badges go stale** after a commit made outside the editor. Trust
  `git status`.

## Do not "fix" these

- **Five frontend reports call endpoints that do not exist.** They are awaiting
  rebuild, not broken. [docs/roadmap.md](docs/roadmap.md#dead-frontend-reports) lists
  each one and what it calls.
- **`manage.py res_stays` fails deliberately.** Fixed-window stay generation was
  replaced by the daily simulation; the guard says so.
- **A payer change can never move a stay into skilled coverage.** Deliberate, and
  correct for traditional Medicare. Recorded as a known simplification.
- **`aspire-admission-logs.py` and `aspire-discharge-logs.py` look unused.** They
  supply the simulation's rules and can rebuild their own table standalone. There is
  a real duplication to remove there, but read
  [docs/roadmap.md](docs/roadmap.md#cleanup) first.

## Verifying claims

This codebase rewards measurement over intuition, and several confident assumptions
in its history turned out to be wrong: that a Python aggregation loop was the
bottleneck when it was the fetch; that skilled census could not reach 35% when it
reaches 37%; that non-skilled stays were 1.6× longer when a biased sample hid the
real 2.7×. Prefer a query against the real database to a plausible inference, and
say which numbers were measured and which were estimated.
