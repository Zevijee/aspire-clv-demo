# Running the demo in Docker

Three containers: `db` (PostgreSQL 18), `api` (FastAPI) and `frontend` (the built
Vite app behind nginx). Nothing else needs installing — no Python, no Node, no
local PostgreSQL.

## First run

```powershell
cp .env.docker.example .env.docker      # set POSTGRES_PASSWORD
docker compose --env-file .env.docker up --build
```

Then open <http://127.0.0.1:5173>.

Use `127.0.0.1`, not `localhost`, if you also run the Vite dev server locally:
`localhost` resolves to IPv6 first and a host dev server on `[::1]:5173` will answer
instead of the container. Changing `APP_PORT` in `.env.docker` avoids the clash
entirely.

`up` never migrates, seeds or restores. Data work is always an explicit command, so
no stray `up` can rebuild a database someone is using.

## Getting data in

The database starts empty, and the API refuses to start without a valid schema —
that is deliberate, not a failure. Choose one of:

**Restore a snapshot (minutes).** Put `aspire.sql.gz` in `docker/initdb/` before the
first `up`. PostgreSQL loads anything in that directory when the volume is created,
so the stack comes up with data and no extra step. This is how to hand the demo to
someone else; see [docker/initdb/README.md](../docker/initdb/README.md).

**Generate it (about ten minutes).**

```powershell
docker compose --env-file .env.docker run --rm reset
```

## Commands

| Command | Does |
| --- | --- |
| `up --build` | Start the stack. No schema or data changes. |
| `run --rm status` | Applied migrations, backfills and staged drafts. |
| `run --rm update` | Migrate, then generate missing days. Safe to repeat. |
| `run --rm reset` | Drop every table and rebuild from 2023-01-01. |
| `run --rm dump` | Write `docker/initdb/aspire.sql.gz` from the running database. |
| `run --rm restore` | Load that file over the current database. |
| `down` | Stop. The data volume survives. |
| `down -v` | Stop and delete the data volume. |

All of them take `--env-file .env.docker`.

## How the pieces connect

The browser only ever talks to the frontend's origin. nginx serves the built assets
and proxies `/api/` to `api:8000`, so there is no cross-origin request and
`API_CORS_ORIGINS` only matters if you publish the API port and call it directly.

Compose builds the whole connection string into `DATABASE_URL` for the containers.
The repository root `.env`, which points at your local PostgreSQL, is never read by
Compose and is excluded from the image.

The API and the seeder are the same image: both import `shared/database`, so the
build context is the repository root rather than `backend/`. Which one runs is a
command, not a separate build.

## Things that will bite you

**The database healthcheck probes TCP on purpose.** While PostgreSQL runs the files
in `docker-entrypoint-initdb.d` it starts a temporary server with `listen_addresses`
empty. A unix-socket probe reports healthy immediately, and the API then starts
against a database whose snapshot is still loading. `pg_isready -h 127.0.0.1` only
succeeds once the real server is accepting connections.

**PostgreSQL 18 moved its data directory.** The volume mounts at
`/var/lib/postgresql`, not `/var/lib/postgresql/data`; 18+ keeps data in a
major-version subdirectory so `pg_upgrade --link` works. Mounting the old path makes
the image refuse to start rather than risk an unmigrated upgrade.

**Snapshots must match the server's major version.** The image is pinned to
PostgreSQL 18 to match a typical local install. A dump taken from a newer server may
not restore into an older one.

**`pg_dump` does not understand a SQLAlchemy URL.** The root `.env` uses
`postgresql+psycopg://`; libpq tools need the `+psycopg` removed. The `dump` service
handles this by connecting with `PGHOST`/`PGUSER` instead of a URL.
