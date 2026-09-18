# Frontend

React 19 and TypeScript report UI, built with Vite. antd for components, recharts
for charts.

## Guidance

Read the root [AGENTS.md](../AGENTS.md) and [STYLE_GUIDE.md](STYLE_GUIDE.md) before
UI changes. The style guide owns shared visual and interaction standards.
[UI context](../docs/ui-context.md) records dated report choices; it does not
restrict which report or module can be built next.

Reuse shared components and utilities. Put feature-specific composition in the
relevant feature and fix shared behaviour in its owning component. The current
directory inventory is not a fixed module roadmap.

## Running it

With the API and database already running (locally or in Docker):

```powershell
npm install
npm run dev
```

Defaults to `http://localhost:8000` for the API, or `VITE_API_BASE_URL`.

Note the port: this dev server binds 5173, and so does the Docker frontend. If both
run, `localhost:5173` resolves to IPv6 and reaches this dev server while the
container sits on IPv4. Use `127.0.0.1:5173` for the container, or change `APP_PORT`
in `.env.docker`.

For the whole stack in containers, see the [Docker guide](../docs/docker.md). Set
`API_PROXY_TARGET` to have Vite proxy `/api` instead of calling the API's origin
directly — `vite.config.ts` reads it, and containers use it so the browser stays on
one origin.

## Which API each report uses

Only Admissions is connected to the current backend. The rest call endpoints that
the backend rebuild has not reimplemented; they render but do not load. See
[docs/roadmap.md](../docs/roadmap.md#dead-frontend-reports).

| Client | Targets | State |
| --- | --- | --- |
| `api/admissionsOverview.ts` | `/adt/admissions/overview`, `/logs`, `/reference/*` | **live** |
| `api/admissions.ts` | fourteen removed `/adt/admissions/*` endpoints | legacy |
| `api/discharges.ts` | `/adt/discharges/*` | not implemented |
| `api/payerChanges.ts` | `/adt/payer-changes` | not implemented |
| `api/netChange.ts`, `api/movementLogs.ts` | `/adt/net-change/*` | not implemented |

`admissionsOverview.ts` is the reference for how a client should look: it reads
paginated reference data once and caches it, builds selection parameters from saved
facility IDs rather than names, and maps payer codes to display labels in one place.

## Contract notes worth knowing

These are properties of the API the components rely on. Full detail in
[docs/backend-structure.md](../docs/backend-structure.md).

- **Location selection is OR within a level, AND across levels.** An empty selection
  means unfiltered; `match_none=true` states an empty selection explicitly. Grouping
  (`group_by`) is independent of selection.
- **Selections use saved IDs, never names.** Drilldowns pass `facility_ids` straight
  through so a page and a modal can hold independent selections against one endpoint.
- **Chart facets omit their own filter.** The payer chart applies the source filter
  but not the payer filter, so alternative payers stay visible and clickable. Do not
  assume every response applies every filter.
- **Every calendar date appears in `daily`**, including days with no activity, so
  trend charts show real gaps rather than skipping them.
- **A selected location with no activity still appears in `locations`** with zeros.
- **Averages divide by calendar days in the range**, not by days with data.
- **Current and prior periods are separate calls.** The frontend computes the
  difference; an unavailable prior period leaves the current report usable.
- **409 means a date range was never generated** — genuinely missing data, distinct
  from a generated day that was simply quiet. Surface it as such rather than as a
  generic failure.
- **Table filter values come from the entire filtered result**, not the current page,
  and the column being opened is excluded from its own options.
