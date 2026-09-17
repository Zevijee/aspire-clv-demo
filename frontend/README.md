# Frontend

React and TypeScript report UI, built with Vite.

## Guidance

Read the root [AGENTS.md](../AGENTS.md) and [STYLE_GUIDE.md](STYLE_GUIDE.md) before UI changes. The style guide owns shared visual and interaction standards. [UI context](../docs/ui-context.md) records dated report choices; it does not restrict which report or module can be built next.

Reuse shared components and utilities. Put feature-specific composition in the relevant feature and fix shared behavior in its owning component. The current directory inventory is not a fixed module roadmap.

## Local development

The default setup runs the frontend, API and PostgreSQL together in Docker. Use the [Docker guide](../docs/docker.md#development-with-live-edits) for live development; no host Node.js or separate API/database startup is required.

For the optional native workflow, run only the frontend from this directory:

```powershell
npm install
npm run dev
```

The API must be running separately. Copy `.env.example` to `.env` if `VITE_API_BASE_URL` needs to differ from the local default. Ensure the backend permits the frontend origin in its CORS configuration.

The scripts in [package.json](package.json) are `dev` (Vite development server), `build` (TypeScript and production bundle), `lint` (Oxlint), and `preview` (serve the built frontend locally). This list describes available commands; tests require an explicit user request under the repository rules.

## Code map

| Area | Location |
| --- | --- |
| Routing and report composition | `src/app/App.tsx` |
| Feature reports and data access | `src/features/` |
| Shared layout, tables, filters, charts, and feedback | `src/shared/components/` |
| Shared hooks, types, and utilities | `src/shared/` |
| Shared styling | `src/App.css` |
| Design tokens | `src/index.css` |

Paths and scripts were reviewed September 17, 2026. Verify them against the current source when they change; this README does not freeze component or report design.
