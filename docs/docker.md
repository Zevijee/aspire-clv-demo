# Docker setup

Open a terminal in your checkout's repository root: the folder containing `compose.yaml`, `backend` and `frontend`. The checkout can live anywhere; no username, drive letter or absolute host path is required. Run every command on this page from that folder.

## Platform requirements

| Host | Container runtime |
| --- | --- |
| Windows | Docker Desktop using Linux containers |
| macOS, including Apple Silicon | Docker Desktop |
| Linux | Docker Engine with the Docker Compose plugin, or Docker Desktop |

Use Compose v2.24.4 or newer. Host Python, Node.js and PostgreSQL are not required. Docker documents the [installation options for each platform](https://docs.docker.com/compose/install/).

The setup targets x86-64 (`linux/amd64`) and ARM64 (`linux/arm64`) Docker hosts. All selected base image tags publish both architectures; no Dockerfile or Compose service forces an Intel-only platform. Images build dependencies inside the target architecture's containers, including Node's native dependencies. Registry architecture metadata was checked; application builds on those platforms have not been executed.

Image metadata: [Python](https://hub.docker.com/v2/repositories/library/python/tags/3.14-slim), [Node](https://hub.docker.com/v2/repositories/library/node/tags/24-bookworm-slim), [PostgreSQL](https://hub.docker.com/v2/repositories/library/postgres/tags/17-bookworm), and [Nginx](https://hub.docker.com/v2/repositories/nginxinc/nginx-unprivileged/tags/stable-alpine).

The documented workflow assumes a local Docker engine. With a remote Docker context, browser ports, host aliases and development bind mounts refer to that remote Docker host, not necessarily the device running the CLI.

This setup was prepared without starting containers, changing a database, or running tests. Docker was unavailable on the authoring machine, so image builds and runtime behavior have not been verified.

## What runs

| Service | Purpose | Host address |
| --- | --- | --- |
| `frontend` | Built React application served by Nginx; `/api` forwards to the API | `http://localhost:5173` |
| `api` | FastAPI and shared reporting code | Internal container network only |
| `db` | PostgreSQL 17 with a persistent named volume | Internal container network only |
| `migrate` | Explicit schema upgrades and demo-target registration | One-off command |
| `seed` | Explicit demo population, catch-up, backfill and resume | One-off command |
| `reporting` | Explicit reporting refresh without generation | One-off command |

The browser uses one origin, including when sharing the application through a tunnel. No browser request points at Docker's `api` hostname or the visitor's `localhost:8000`. API and PostgreSQL do not claim host ports 8000 or 5432. `APP_PORT` changes the frontend port if 5173 is already occupied.

Migrations and seeders are separate tool services. Ordinary startup never applies migrations or generates residents. Healthchecks coordinate startup; the API health endpoint confirms the process is alive, not that reporting data has been populated. See Docker's [startup dependency documentation](https://docs.docker.com/compose/how-tos/startup-order/) and [one-off profile behavior](https://docs.docker.com/compose/how-tos/profiles/).

## Configure once

If `.env.docker` does not exist yet, duplicate `.env.docker.example` as `.env.docker` using your editor/file manager, or use the command for your shell:

| Shell | Copy command |
| --- | --- |
| PowerShell | `Copy-Item .env.docker.example .env.docker` |
| Bash / Zsh | `cp .env.docker.example .env.docker` |

All subsequent `docker compose` commands work unchanged in these shells.

Edit `.env.docker` and choose a local `POSTGRES_PASSWORD` before the first database startup. This file is ignored by Git. The existing root `.env` is neither overwritten nor mounted into the containers. Passwords are passed as separate connection fields, so the bundled database password needs no URL encoding; use a single-quoted `.env` value for literal `$` characters.

Continue with the default stack below; Docker starts PostgreSQL for you. **The Docker database is separate and initially empty; existing local data is not automatically copied into it.**

## Start the default stack

Use the base Compose file to start the frontend, API and PostgreSQL together with persistent database storage. No separate PostgreSQL installation or service is needed. This does not transfer existing local history. To preserve that exact history in Docker, perform a separately planned PostgreSQL backup/restore, matching compatible PostgreSQL versions; do not populate new data over a restored database.

In the first terminal:

```sh
docker compose --env-file .env.docker up --build --abort-on-container-exit
```

Leave it running. In a second terminal at the repository root, initialize the new database explicitly, one command at a time:

```sh
docker compose --env-file .env.docker run --rm --no-deps migrate upgrade
docker compose --env-file .env.docker run --rm --no-deps migrate configure-demo --instance-id aspire-docker
docker compose --env-file .env.docker run --rm --no-deps seed populate --through today
```

Use your configured `DOCKER_DEMO_INSTANCE_ID` if you changed the example value. `populate` creates missing demo history; it is not a full reset. Open `http://localhost:5173` after the data operation finishes.

Database data stays in the project's `postgres_data` named volume across ordinary stops, image rebuilds and `down`. Changing `POSTGRES_PASSWORD` after initial creation does not change the existing PostgreSQL role's password; coordinate an explicit database credential update rather than deleting the volume. Keep the PostgreSQL major version stable until performing a planned database upgrade.

## Normal commands

These examples use the bundled database. The optional legacy transition below explains the override for an external database.

```sh
# Catch up every missing day, including missed runs.
docker compose --env-file .env.docker run --rm --no-deps seed update --through today

# Plan a narrow change without database writes.
docker compose --env-file .env.docker run --rm --no-deps seed rebuild --dataset admissions --facility ASP-001 --from 2026-09-01 --through 2026-09-17 --preview

# Recompute stored hospital reporting from existing facts.
docker compose --env-file .env.docker run --rm --no-deps reporting --dataset referring_hospitals --from 2023-09-01 --through 2026-09-17

# Continue a recorded failed run.
docker compose --env-file .env.docker run --rm --no-deps seed resume --run-id YOUR_RUN_ID

# Inspect container logs.
docker compose --env-file .env.docker logs --tail 100 api
```

Use the actual source dates and run IDs for your data. `--no-deps` keeps one-off commands from secretly starting background dependencies; start the chosen stack in its foreground terminal first. Named tool commands do not require manually enabling the `tools` profile.

## Development with live edits

Add the development override. It uses Vite with an API proxy and Uvicorn reload. `DEV_WATCH_POLLING=true` enables file-change polling for mounted filesystems on any host; set it to `false` in `.env.docker` when native filesystem notifications work, such as a native Linux checkout:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml up --build --abort-on-container-exit
```

For the existing local database, append `-f compose.external-db.yaml` before `up`. Use the same file combination for migration/seed/reporting commands, so they see current backend source too.

Frontend source/config mounts retain Linux `node_modules` from the image. Backend code is mounted into the API and tool services. Rebuild images after dependency manifest or lockfile changes; neither container installs packages on every startup. The default built frontend requires an image rebuild after UI changes.

The backend passes the setting to [watchfiles' polling control](https://watchfiles.helpmanual.io/api/watch/#force-polling); the frontend uses Vite's equivalent watch option. Reporting dates use `REPORTING_TIMEZONE`, not the host device's timezone.

All bind-mount paths are relative to the repository. Docker Desktop must have access to the checkout folder. On Linux, source files must be readable by the non-root container users; generated frontend dependencies stay in the image rather than being written into the host checkout. The default built stack does not bind-mount host source files.

## Source loading and reporting as separate steps

New seed runs load each source dataset across the selected facilities, then build reporting summaries over grouped affected scopes. Migrations through version 6 must be explicitly applied after any running old seed finishes. It adds publication tracking and reporting indexes; no full reseed is required.

For development, after migration and with the stack running:

```sh
# Step 1: load source data only; save the printed load ID.
docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml run --rm --no-deps seed populate --through today --sources-only
# Step 2: build reports from that load, without generating source data.
docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml run --rm --no-deps reporting --load-id LOAD_ID
```

Omit `--sources-only` to run both phases in sequence. Resume interrupted loads using `seed resume --run-id RUN_ID`; already completed source stages are skipped. Existing saved version-1 runs keep the legacy runner for recovery. Reports display an explicit unavailable state until the pending load is fully published. No database operation was executed to prepare this change.

## Stop behavior

The documented startup runs in the foreground. Ctrl+C stops the stack, and `--abort-on-container-exit` stops the other services if one exits. Restart policies are disabled. This follows [Compose's foreground shutdown behavior](https://docs.docker.com/reference/cli/docker/compose/up/).

Docker containers are owned by the Docker daemon on every supported host. Forcibly killing the terminal or Compose process can leave containers running. After an abrupt close, explicitly stop them:

```sh
docker compose --env-file .env.docker down
```

Include the same overrides when stopping a development or external-database stack. Ordinary `down` preserves PostgreSQL data. Do not add `--volumes` unless deleting the Docker database is intentional. Stop any old `run_app.py` terminal before using the same frontend port.

## Optional legacy transition: keep an existing external database

Use this optional override only when deliberately keeping an existing external database during a transition. The default local setup runs PostgreSQL in Docker. The frontend/API/tooling run in Docker and connect to the specified database host. The bundled database service stays disabled.

Add `EXTERNAL_DATABASE_URL` to `.env.docker` using the existing database and credentials. For a database on the Docker host, replace `localhost` with `host.docker.internal`; the override explicitly maps this alias through Docker's `host-gateway` on Linux as well as Docker Desktop. A custom installation can set `DOCKER_HOST_GATEWAY` to its reachable host address. For a remote database, use its actual reachable DNS name instead. PostgreSQL must listen on an interface reachable from the containers and allow their connections; a host loopback-only listener may not be reachable on native Linux.

Keep URL-encoded credentials. Set `DOCKER_DEMO_INSTANCE_ID` to the database's existing configured demo instance ID (for example, `aspire-local`); do not give an already-registered database a new identity.

In the first terminal:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.external-db.yaml up --build --abort-on-container-exit
```

In a second terminal at the repository root, run each needed command separately, stopping if one fails:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.external-db.yaml run --rm --no-deps migrate upgrade
```

If the database has not been registered as demo yet, explicitly register it with the same ID configured in `.env.docker`:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.external-db.yaml run --rm --no-deps migrate configure-demo --instance-id aspire-local
```

To adopt existing legacy data into the new shared tables and catch up missing dates:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.external-db.yaml run --rm --no-deps seed backfill --backfill-name canonical_sources
docker compose --env-file .env.docker -f compose.yaml -f compose.external-db.yaml run --rm --no-deps seed update --through today
```

No full reset is needed for this path. It does run the explicit migration/backfill/update you request against the existing database; Docker is not a copy or rollback of that database. If you already completed the migration and adoption, skip those steps and use update when needed.

## Deployment boundary

Images use non-root application users, and the frontend production target serves built assets. This Compose configuration is a local/demo setup: production still needs its own secrets, authentication/authorization, HTTPS, backups and deployment policy. Adding Docker does not claim that those separate application requirements have been completed.
