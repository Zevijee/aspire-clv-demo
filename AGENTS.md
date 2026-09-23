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
| How is this hosted for other people | [docs/deploying.md](docs/deploying.md) |
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
  four event sources. A *time-grain rollup* of an existing fact table is the one
  allowed exception, and it has to earn its place by measurement:
  `monthly_payer_census_facts` and `monthly_referral_facts` are both rollups, not
  new event sources, and both were built because a report reads whole years at
  once. Referring Hospital still needs no new *event* table — `source_name` was
  already at the grain of `daily_admission_facts`, which is what
  `monthly_referral_facts` rolls up.
- **Keep dimension keys at the grain** (`payer_id`, not `payer_type`) *when the
  finer grain is close to free*. For admissions and discharges it measured free.
  It is not a universal rule: at `payer_id` grain `daily_payer_change_facts` came to
  **99.9% of its source rows**, which is a copy rather than a summary, so payer
  change and payer census facts use `payer_type` and leave plan names in the logs.
  Measure the row count at both grains before choosing.
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
| Payer change reporting, from saved periods | `payer_change_logs --regenerate`, ~4 s |
| Referring hospital months, from the daily facts | `referrals_summary --regenerate`, ~1 s |
| Monthly trending, from saved periods | `monthly_adt_summary --regenerate`, ~6 s |
| Net change / payer census | `net_change_summary --regenerate`, ~8 min |
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
python manage.py discharges_summary --regenerate
python manage.py payer_changes_summary --regenerate
python manage.py net_change_summary --regenerate      # ~8 min; rebuilds 2.5M rows
python manage.py monthly_adt_summary --regenerate     # ~6 s, independent of the above
python manage.py referrals_summary --regenerate       # ~1 s; rolls the daily facts up by month
python manage.py referring_hospitals --regenerate     # the 384-hospital catalogue
python manage.py admission_logs --regenerate    # rebuild one table from saved stays
python manage.py discharge_logs --regenerate
python manage.py payer_change_logs --regenerate
python backend/manage.py serve --reload         # from the repository root
npm --prefix frontend run dev                   # frontend on 127.0.0.1:5173
```

Everything runs on this machine against one PostgreSQL 18 database. There is no
local Docker workflow; `Dockerfile` exists only to deploy the API and the daily
generation job. See [docs/deploying.md](docs/deploying.md).

## Traps that have already cost time

- **`postgresql+psycopg://` is a SQLAlchemy URL.** `pg_dump`, `psql` and every other
  libpq tool need `+psycopg` removed. Passing it whole makes `pg_dump` hang without
  connecting and without an error.
- **Settings need the `API_` prefix.** `API_CORS_ORIGINS`, `API_TIMEZONE` and so on.
  `DATABASE_URL` is aliased and does not. A bare `CORS_ORIGINS` in `.env` is silently
  ignored — and currently is.
- **`API_CORS_ORIGINS` is parsed as JSON**, so it needs a JSON array, not a
  comma-separated list. A hosted frontend needs its own origin listed, and Vercel
  preview deployments each get a different one.
- **The frontend bakes `VITE_API_BASE_URL` in at build time** and falls back to
  `http://localhost:8000`. On a hosted build that fallback means every visitor's own
  machine, so `vite.config.ts` fails the build when Vercel sets `VERCEL` and the
  variable is missing.
- **Alembic autogenerate writes neither CHECK constraints nor table drops.** Both
  must be added by hand, and a `nullable=False` column added to a populated table
  fails without a default. Always read the generated migration.
- **Schema edits go in `shared/database/staged/schema.py`**, never the active file.
  `manage.py stage` creates the draft; `update` publishes it.
- **VS Code's git badges go stale** after a commit made outside the editor. Trust
  `git status`.
- **There is one database.** It used to be three -- two local and one in a
  container, at the same schema revision with different data -- so a migration had
  to be applied more than once and forgetting one made the API fail its readiness
  check while every request hung with no error in the browser. Both entry points now
  print the database they resolved, `aspire_analytics @ host:port`. Keep it to one.
- **Use `127.0.0.1` in `DATABASE_URL`, never `localhost`.** `localhost` resolves to
  `::1` first, and if Postgres listens on IPv4 only that attempt is refused after a
  two-second timeout before falling back. Every connection pays it. Measured:
  `manage.py status` took 2m10s through `localhost` and under a second through
  `127.0.0.1`.
- **Deployed code and the database migrate together.** An image built from an
  earlier commit can be several migrations behind, and the API then refuses to start
  against a database that is ahead of it. The deploy has to run
  `manage.py upgrade` before the new version serves traffic. This is why
  `render.yaml` sets a pre-deploy command.
- **A generator that carries a running balance cannot be rebuilt for one day.**
  `net_change_summary` and `monthly_adt_summary` recompute from the first affected
  row onward. `net_change_summary` has an `extend` path for a contiguous tail only,
  and falls back to a full rebuild for anything else.

## Do not "fix" these

- **Live Census calls an endpoint that does not exist.** It is awaiting rebuild, not
  broken. Admissions, Discharges, Payer Changes, Net Change, Monthly ADT Trending and
  Referring Hospital all work end to end.
  [docs/roadmap.md](docs/roadmap.md#dead-frontend-reports) lists what is left.
- **`HospitalPerformanceLocations.tsx` and `ReferringHospitalsModal.tsx` are
  orphans.** Nothing imports them and they call removed endpoints. They were left in
  place rather than deleted alongside the Referring Hospital rebuild; see
  [docs/roadmap.md](docs/roadmap.md#cleanup).
- **`manage.py res_stays` fails deliberately.** Fixed-window stay generation was
  replaced by the daily simulation; the guard says so.
- **A payer change can move a stay only from managed Medicare into Original
  Medicare, never into any other skilled payer.** Medicare Advantage disenrolment
  mid-stay is real, so `medicare_hmo` and `medicare_comm` may move to `medicare`.
  It continues the same 100-day allowance rather than restarting it, which is why
  every other skilled destination is still blocked. See `MANAGED_MEDICARE` and
  `MANAGED_DISENROLMENT_SHARE` in `aspire-res-stays.py`.
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
