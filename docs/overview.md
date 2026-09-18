# Why this demo exists

Clearview is the design vehicle for a reporting product that does not have a data
pipeline yet. The purpose is to get the dashboards right — the metrics, the
groupings, the drilldowns, the way a portfolio of 253 facilities reads at group,
state, portfolio, region and facility level — before committing to an ETL build
against a real electronic health record.

That ordering is deliberate. Report design is cheap to change here and expensive to
change once a pipeline is emitting into a warehouse that dashboards already read.

## What that means for the data

The dataset is generated rather than copied, but it is not arbitrary. A dashboard
is only useful for design review if the numbers on it are plausible, so the
simulation targets real skilled-nursing behaviour: Medicaid-heavy census with
long-stay residents, short skilled stays that turn over quickly, weekday-driven
admissions, seasonal census movement, and facilities that genuinely differ from one
another. [docs/generators.md](generators.md) describes how, and
[docs/scaling.md](scaling.md) records what was measured against industry norms.

Facility count and history length matter for the same reason. Ten facilities over
six months is fast to generate and useless for reviewing a portfolio dashboard: the
group, state and region levels have nothing to say, and a ranking chart of ten rows
answers no question that a table would not. The demo runs the full 253 facilities
over roughly four years because the aggregate levels are the thing being validated.

## The pipeline this is designed to meet

The real pipeline will **full-refresh every run**, roughly every three hours.

That is a considered choice, not a shortcut. Electronic health records permit
retroactive edits constantly — late documentation, corrected payers, backdated
discharges — and detecting what changed requires change tracking that the source
systems do not reliably provide. Rebuilding from source is the correct engineering
answer, and it is the default in most warehouse tooling.

Two consequences shape this codebase:

**Rebuild cost is the critical path, not query cost.** Anything derived is
recomputed on every run, so the cost of recomputing it is paid continuously rather
than once. This is the reasoning behind the reporting store described below.

**Runtime is not the constraint.** A three-hour window is generous; a full rebuild
of every fact table at current scale is minutes. Performance work in this repository
is therefore aimed at the *development* loop — how long it takes to change a
distribution and look at the result — not at production throughput.

## Why reporting tables are facts, not documents

The reporting store was originally one JSONB document per scope per day:
`daily_admission_summaries`, keyed by (level, scope_id, date), holding a
pre-aggregated payload for group, state, portfolio, region and facility.

It was replaced by `daily_admission_facts`, one row per
(date, facility, payer, referral source) that had admissions, with additive
measures. Parent scopes are `GROUP BY` results computed at query time.

The measured difference on identical data:

| | Documents | Facts |
| --- | --- | --- |
| Storage | 1,101 MB | 89 MB |
| Rows | 416,736 | 349,458 |
| Full rebuild | ~180 s | ~21 s |
| One-year report | 1,040 ms | 150–250 ms |

The storage and rebuild numbers matter because of full refresh: three minutes per
summary table, every run, forever, multiplied by however many reporting tables the
product ends up with.

The read number is the one that surprised us. The document design was supposed to
buy fast reads, but it pre-aggregated at the wrong grain — per scope *per day* — so
a one-year report still had to fetch and sum 92,345 documents in Python. Aggregating
narrow rows in PostgreSQL is both faster and smaller.

The deeper reason, though, is change. A metric baked into 416,736 JSON documents can
only be changed by rewriting all of them. With facts:

- a metric derivable from existing dimensions costs **nothing** — it is a different
  `GROUP BY`
- a new additive measure is a column plus a backfill
- only a change of grain requires regeneration

This project had already hit that wall once. `medicaid_pending_admissions` was added
as an optional payload field that older dates defaulted to zero, because rewriting
every document was not worth it. That compromise is gone.

## Staying swap-compatible

The intent is that the demo and the real pipeline land the same shapes, so the
dashboards can be pointed at real data by changing a connection string.

A fact table with dimension keys and additive measures is the standard output of a
warehouse transformation — it is what dbt models emit and what dimensional modelling
has prescribed since Kimball. Matching *facts* is therefore more likely to be
swap-compatible than matching a document store, not less.

The boundary to protect is the API. The reports read through
`backend/app/adt/admissions/service.py`; nothing else queries the reporting tables.
As long as that contract holds, the storage underneath can change — including being
replaced by real tables — without touching the frontend.

## Scope and honest limits

This is a local, read-only demo. There is no authentication and no
facility-access authorisation; selecting locations narrows data but is not a
security boundary. The simulation is a demo artifact and will never run in
production, which is why its performance matters only to developers.

Known simplifications are recorded in [docs/roadmap.md](roadmap.md) rather than
hidden — most notably that a payer change can never move a stay *into* skilled
coverage, so mid-stay Medicare Advantage conversions do not appear in the data at
all.
