# Project instructions

## Scope and changing priorities

- The user's current request determines which module/report to build and which existing behavior to change. There is no prescribed module order.
- Dated plans, audits, schema proposals, and UI snapshots are context, not permanent product restrictions or prerequisite checklists. Verify their factual claims against current code.
- Do not ask for reconfirmation merely because a clear new request differs from an older plan or UI choice. Preserve unrelated behavior and implement the requested scope and actual technical dependencies.
- Keep durable rules separate from report contracts, demo scenario choices, implementation status, and proposals. Do not convert a current limitation, temporary UI experiment, or existing module list into a restriction on future work.

## Frontend and UI

- Before changing UI, read [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md), including its shared interaction patterns and component map. Report-specific historical choices live separately in [docs/ui-context.md](docs/ui-context.md).
- Reuse shared components and tokens. Fix shared behavior in its owning component rather than creating report-specific copies or CSS workarounds.
- Preserve UI choices outside the requested change; verify dated implementation descriptions against code. The no-tests rule below also applies to frontend work.

## Backend and seeding architecture

- Before changing backend structure, database models/migrations, report APIs, reporting calculations, seeders, or ingestion, read [instructions.md](instructions.md).
- It defines separate API and seeding packages, shared source/reporting ownership, incremental report development, and targeted updates instead of routine full reseeds.
- The schema and optimization documents it references are review proposals, not authorization to execute migrations, seeders, or a full refactor.

## Seed history

- Every date-based seeder must use the shared `SeedWindow`: start on the first day of the month 36 months before the as-of date, and end on the as-of date, inclusive.
- Preserve all 36 complete months plus the current month to date. Never start on the same day-of-month three years ago or approximate the range with a fixed day count; partial first months skew report averages.
- Keep related date-based datasets aligned to this shared window, including known zero-activity days. Admissions, discharges, census, and payer changes are examples, not the complete list.

## Tests

- Do not write, add, modify, or run tests unless the user explicitly requests it.
- Do not run test suites automatically after implementation or bug fixes.
- The user will report broken behavior and decide when tests are needed.
- Complete requested changes without spending time or tokens on unsolicited tests.
