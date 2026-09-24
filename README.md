# Clearview

A skilled-nursing analytics demo for Aspire Health Group: a React dashboard over a
synthetic dataset of resident admissions, discharges and payer activity across 253
facilities and roughly four years of daily history.

The data is generated, not copied. A day-by-day simulation produces admissions,
discharges, payer periods and census with realistic distributions, so the reports
can be designed and reviewed before any real pipeline exists. See
[docs/overview.md](docs/overview.md) for why the demo is built this way.

## Run it

Needs Python 3.11+, Node 20+ and PostgreSQL 18 on this machine. Three processes:
the database, the API and the frontend.

### 1. The database

One database, and nothing else in this project creates one. Put its URL in a root
`.env`:

```
DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/aspire_analytics
```

Use `127.0.0.1`, never `localhost`. `localhost` resolves to `::1` first, and if
Postgres is listening on IPv4 only that attempt is refused after a two-second
timeout before falling back — every connection pays it. Measured: `manage.py status`
took 2m10s through `localhost` and under a second through `127.0.0.1`.

### 2. Generate the data

```powershell
python -m pip install -r sandbox-data/requirements.txt
python -m pip install -r backend/requirements.txt

cd sandbox-data
python manage.py update            # migrate, then generate missing days
```

On an empty database `update` does everything: it creates the schema, then
generates every day from 2023-01-01. That takes about 9.5 minutes, plus 8 more for
`net_change_summary`. Afterwards the same command adds only the days that are
missing, which takes seconds, and it is safe to repeat.

Every command prints the database it resolved, so you can always see what it is
about to touch:

```text
Sandbox data | status
  Database    aspire_analytics @ 127.0.0.1:5432
```

### 3. The API and the frontend

```powershell
python backend/manage.py serve --reload     # from the repository root
```

```powershell
cd frontend
npm install
npm run dev
```

The API listens on <http://127.0.0.1:8000>, with documentation at `/docs`. The
frontend is on <http://127.0.0.1:5173> and calls the API at that address, or
`VITE_API_BASE_URL`. The API refuses to start against an unmigrated database on
purpose, so run `update` first.

### Deploying it

`Dockerfile` builds one image that runs either the API or the seeder — which one is
a command, not a separate build. That is the only thing Docker is used for here;
there is no local Docker workflow. See [docs/deploying.md](docs/deploying.md).

## What lives where

```text
backend/          FastAPI read-only reporting API
  app/            one package per feature: routes, service, schemas
sandbox-data/     the data generator and its command line
  base.py         run order, batching, COPY and upsert machinery
  source_data_generators/   the ADT simulation and reference data
  summary_generators/       derived reporting tables
shared/database/  the schema, migrations, backfills and lifecycle locking
                  imported by both the API and the generator
frontend/         React 19 + Vite + antd + recharts
Dockerfile        one image for deployment: API or seeder, by command
docs/             everything below
```

## Documentation

| Document | What it answers |
| --- | --- |
| [docs/overview.md](docs/overview.md) | Why this demo exists and how it relates to the real pipeline |
| [docs/backend-structure.md](docs/backend-structure.md) | API architecture, every endpoint, how to add a report |
| [docs/generators.md](docs/generators.md) | How the simulation works and which constant tunes what |
| [docs/database-workflow.md](docs/database-workflow.md) | Schema changes, migrations, backfills, regenerating data |
| [docs/database-schema.md](docs/database-schema.md) | Generated table and column reference |
| [docs/scaling.md](docs/scaling.md) | Measured performance, storage, and what breaks at scale |
| [docs/deploying.md](docs/deploying.md) | Hosting the frontend on Vercel, and what has to sit behind it |
| [docs/roadmap.md](docs/roadmap.md) | What is next and what is deliberately unfinished |
| [docs/ui-context.md](docs/ui-context.md) | Report-specific interface history |
| [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md) | Shared components and interaction patterns |
| [AGENTS.md](AGENTS.md) | Working rules, invariants and known traps |

## Current state

Six reports work end to end: **Admissions**, **Discharges**, **Payer Changes**,
**Net Change**, **Monthly ADT Trending** and **Referring Hospital**. Each of the
first five has an overview built on a fact table, a logs tab reading source rows,
filter options and CSV export. Referring Hospital is the exception in shape: one
table over a fixed 36-month window, with a per-hospital detail view.

**Live Census** also works: each facility's current census and skilled census
against last month's average daily census, drilled down from state to facility.
The other Census reports are placeholders.

Measured response times on the full dataset, 30-day and 1-year ranges:

| Endpoint | 30 days | 1 year |
| --- | --- | --- |
| Admissions overview | 5 ms | 5 ms |
| Discharges overview | 28 ms | 156 ms |
| Payer Changes overview | 23 ms | 144 ms |
| Net Change overview | 46 ms | 399 ms |
| Monthly trend | 47 ms | 128 ms |
| Referring Hospital, all 384 | — | 105 ms (fixed 36 months) |

Net Change reads the largest table in the database (2.5M rows) and is the slowest
of the five, but answers from a single scan.
