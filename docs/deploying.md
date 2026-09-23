# Deploying the demo

Four things have to be hosted: the frontend, the API, a PostgreSQL database, and a
job that generates each day's synthetic data. One platform can do all four, and
[`render.yaml`](../render.yaml) declares them.

There is no local Docker workflow — see the [README](../README.md) for how to run
this on your machine. `Dockerfile` exists only for the two services below that need
Python, and it builds one image that runs either the API or the seeder, because
which one runs is a command rather than a separate build.

## What goes where, and why

| Service | How | Why |
| --- | --- | --- |
| Frontend | Static files from `frontend/dist` | It is static. A CDN serves it better and cheaper than a container running nginx. |
| API | Docker, from `Dockerfile` | Needs Python, `shared/database` and a long-lived connection pool. |
| Daily generation | Docker, same image, `manage.py update` | Same dependencies as the API; only the command differs. |
| Database | Managed PostgreSQL | 1,393 MB measured at full scale. |

The frontend builds with `VITE_API_BASE_URL` empty, which makes every request a
relative `/api/v1/...` path — verified: an empty base leaves no absolute URL in the
bundle at all. A rewrite on the static site forwards `/api` to the API service, so
the browser only ever talks to one origin and **no CORS configuration is needed**.

## Three things that will bite

**The database must migrate before the new API serves traffic.** The API refuses to
start against an unmigrated database, on purpose. Without a pre-deploy step, a push
that carries a migration gives you an API that fails its readiness check while every
request hangs with nothing in the browser to explain it. `render.yaml` sets
`preDeployCommand: python sandbox-data/manage.py upgrade` for exactly this.

**Pushes must not regenerate data, and do not.** The frontend and API rebuild, the
database keeps its rows, and only the scheduled job adds days. A full rebuild is
about 18 minutes and is only ever needed when a generator rule changes — see the
cost table in [AGENTS.md](../AGENTS.md).

**Cron has no timezone.** Schedules are UTC, while the simulation's day comes from
`BaseGenerator.SIMULATION_TIMEZONE` in `sandbox-data/base.py`, a constant set to
`America/New_York`. Noon there is 16:00 UTC in summer and 17:00 in winter. Any
mid-morning hour stays inside the right simulated day; earlier is slightly better,
because a visitor in a timezone ahead of you asks for a date that may not be
generated yet.

## Getting the data there

You do not push it. Generation is deterministic — the same `facilities.json` and
`SEED = 42` reproduce the same distributions — so the host builds its own copy. No
dump in the repository, no release asset, no restore step, and none of the
`pg_dump` URL traps.

`manage.py update` on an empty database migrates it and then generates every day
from 2023-01-01: about 9.5 minutes plus 8 more for `net_change_summary`. That is
the scheduled job's own command, so its first run seeds everything and every run
afterwards has a single day to add. Trigger it by hand once rather than waiting for
the schedule.

Note that the copy it builds is *equivalent*, not byte-identical to yours: the
opening cohort's stay lengths depend on the date you seed, so row counts differ
slightly between two databases seeded on different days.

## If you do not want to pay for 1.4 GB

No free Postgres tier fits — Render, Neon and Supabase all start at 0.5 GB — so
budget for the database and the API, or shrink the hosted dataset.

**Trimming** works through `sandbox-data/hard_coded_data/facilities.json` and
`SIMULATION_START` in `sandbox-data/base.py`; fewer facilities and less history
shrink it close to proportionally. The cost is the thing
[overview.md](overview.md) says the demo exists to show: 253 facilities over four
years is what makes the group, state, portfolio and region levels worth reviewing.

**Or publish the code only.** GitHub already shows it. That is the honest option
when the goal is for people to read what was built rather than click it.

## Vercel, if you would rather split it

[`vercel.json`](../vercel.json) hosts the frontend alone: it sets the install and
build commands, publishes `frontend/dist`, rewrites every path to `/index.html` for
React Router, and sets the cache headers. Vercel cannot run this API — its Python
functions are per-invocation, and the API holds a pool and a session-level advisory
lock across each request — so the API and database still need one of the hosts
above, making two platforms instead of one.

Splitting it also brings CORS back, because the frontend is then on a different
origin from the API:

```
Vercel →  VITE_API_BASE_URL     https://your-api-host
API    →  API_CORS_ORIGINS      ["https://your-project.vercel.app"]
```

`API_CORS_ORIGINS` is parsed as JSON and needs the `API_` prefix; both are recorded
traps in [AGENTS.md](../AGENTS.md). Preview deployments each get their own URL.

`VITE_API_BASE_URL` is read at build time, so changing it needs a redeploy. Leaving
it unset makes the Vercel build fail on purpose: every API client otherwise falls
back to `http://localhost:8000`, which on a hosted build means each visitor's own
machine. The guard in `vite.config.ts` keys on Vercel's own `VERCEL` variable, so it
never affects a local build.

## What a visitor sees with no API behind it

The shell, the navigation and every report frame render. Each KPI row, chart and
table shows its own error state with a retry, because the frontend handles loading,
success, empty and error explicitly — see
[STYLE_GUIDE.md](../frontend/STYLE_GUIDE.md). Nothing crashes and nothing looks
accidentally broken. No numbers appear either.
