# Clearview

A skilled-nursing analytics demo for Aspire Health Group: a React dashboard over a
synthetic dataset of resident admissions, discharges and payer activity across 253
facilities and roughly four years of daily history.

The data is generated, not copied. A day-by-day simulation produces admissions,
discharges, payer periods and census with realistic distributions, so the reports
can be designed and reviewed before any real pipeline exists. See
[docs/overview.md](docs/overview.md) for why the demo is built this way.

## Run it

### Docker, about 30 seconds

Needs Docker only. No Python, Node or PostgreSQL.

```powershell
cp .env.docker.example .env.docker      # set POSTGRES_PASSWORD
docker compose --env-file .env.docker up --build
```

Open <http://127.0.0.1:5173>. Use `127.0.0.1` rather than `localhost`: if you also
run the Vite dev server it holds `[::1]:5173` and will answer instead.

The database starts empty and the API refuses to start without a schema. Put a
snapshot at `docker/initdb/aspire.sql.gz` before the first start and PostgreSQL
restores it automatically, or generate one with
`docker compose --env-file .env.docker run --rm reset` (about ten minutes). The
snapshot is not in this repository; see [docs/docker.md](docs/docker.md).

### Docker, with reload

Mounts the source and reloads both services on edit, instead of serving a build.

```powershell
docker compose --env-file .env.docker up api-dev frontend-dev
```

Frontend on <http://127.0.0.1:5173>, API on <http://127.0.0.1:8000>. Only rebuild
(`--build`) after changing `requirements.txt` or `package.json`.

### Locally

Needs Python 3.11+ and a PostgreSQL 18 database. Put its URL in a root `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/your_database
```

```powershell
python -m pip install -r sandbox-data/requirements.txt
python -m pip install -r backend/requirements.txt

cd sandbox-data
python manage.py update            # migrate, then generate missing days
cd ..
python backend/manage.py serve --reload

cd frontend
npm install
npm run dev
```

The API listens on <http://127.0.0.1:8000>, with documentation at `/docs`. The
frontend defaults to that address, or `VITE_API_BASE_URL`.

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
docker/initdb/    where a database snapshot goes
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
| [docs/docker.md](docs/docker.md) | Containers, snapshots, and the traps in them |
| [docs/roadmap.md](docs/roadmap.md) | What is next and what is deliberately unfinished |
| [docs/ui-context.md](docs/ui-context.md) | Report-specific interface history |
| [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md) | Shared components and interaction patterns |
| [AGENTS.md](AGENTS.md) | Working rules, invariants and known traps |

## Current state

Five reports work end to end: **Admissions**, **Discharges**, **Payer Changes**,
**Net Change** and **Monthly ADT Trending**. Each has an overview built on a fact
table, a logs tab reading source rows, filter options and CSV export.

**Referring Hospital** and **Live Census** still call endpoints that do not exist.
[docs/roadmap.md](docs/roadmap.md) lists what each needs. Referring Hospital needs
no new table — `source_name` is already at the grain of `daily_admission_facts`.

Measured response times on the full dataset, 30-day and 1-year ranges:

| Endpoint | 30 days | 1 year |
| --- | --- | --- |
| Admissions overview | 5 ms | 5 ms |
| Discharges overview | 28 ms | 156 ms |
| Payer Changes overview | 23 ms | 144 ms |
| Net Change overview | 175 ms | 1,324 ms |
| Monthly trend | 47 ms | 128 ms |

Net Change overview is the outlier and is known: it scans its fact table three
times for one response where once would do.
