# Backend refactor plan

Planning snapshot: September 17, 2026. Not a permanent module order or an assertion that these steps have been completed. Verify the repository and latest user request before using it.

For the subsequently prepared code and pending database rollout, read [the implementation status](backend-refactor-status.md). This planning snapshot is retained as design context.

Follow [instructions.md](../instructions.md) for durable engineering rules. The user may choose any module or report next. Only concrete technical dependencies justify prerequisite work; an unfinished milestone here does not block unrelated feature development.

The workstreams below describe a possible transition, not a required sequence of development stages. Select or combine the parts relevant to the user's request and their technical dependencies. Neither reading this plan nor preparing code authorizes a whole-application rewrite or data regeneration. Carry explicit authorization forward without repeatedly asking for it.

### Contracts and remaining decisions

- Use the report audit to record current behavior, defaults and APIs.
- Resolve definitions that materially affect stored data: census/temporary leave, occupancy denominator, empty vs available beds, readmission scope, distinct residents, multi-payer in/out, incomplete baselines and hierarchy attribution.
- Review the shared identities and source entities needed by the selected work. Include whichever module the user requests; do not impose a module sequence.
- Mark each existing report prototype/defined/optimized honestly.

Deliverable: reviewed shared source contract and report contracts; no database run implied.

### Package separation

- Move API entrypoint/routes/schemas/queries under `backend/api`.
- Move demo generators/planner/runner/config under `backend/seeding`.
- Place canonical models/migrations/persistence under `backend/data`; pure rules under `backend/domain`; reporting publication outside both API and seeding.
- Remove API/reporting imports of generator constants and import-time DB reflection.
- Update packaging, launchers and settings paths explicitly. Keep thin compatibility entrypoints during transition; legacy modules forward into new ownership, never the reverse.
- Preserve `run_app.py` terminal-owned process cleanup and current URLs.
- Do not combine these moves with metric changes or data regeneration.

Deliverable: clear import boundaries and existing behavior preserved in code.

### Shared identities and histories

- Add the approved resident, stay, payer type/payer/plan, reference identity and source-mapping migrations.
- Add bed/absence/reservation structures where required by the selected reports. Other domain entities follow their own requested scope.
- Prepare a scoped backfill that maps existing IDs and histories; do not invent resident merges or replace admission dates.
- Prepare compatibility reads so existing reports can transition incrementally.
- Record unresolved source ambiguities rather than silently fabricating normalized history.

Deliverable: migration/backfill code and an explicit application plan. Execute only within the user's authorization for database changes.

### Targeted seeding

- Split generation by source entity family with stable keys and independent randomness.
- Implement scoped planning, idempotent upserts, coverage, checkpoints, backfills and resume.
- Introduce changed-field dirty dependencies instead of global generator-version rebuilds.
- Handle opening state and daily catch-up over the shared SeedWindow.
- Demonstrate through code review and, when requested, controlled runs that payer renames, new references, coverage updates and report refreshes do not rebuild admissions.

Deliverable: targeted seed operations; full reset remains an explicit separate operation.

### Shared reporting publication

- Move all calculations used by both demo and future production into reporting/domain.
- Build event/current-state projections and coverage-aware daily summaries required by settled reports.
- Add dirty scope propagation, staging/batching, coherent publication and cache invalidation.
- Existing prototype reports may continue using their explicit current read paths during the transition.

Deliverable: source-independent refresh pipeline with no fake-generation imports.

### Optimization of selected reports

Choose report priorities from the user's current request and observed bottlenecks. There is no required report or module order, and other reports need not be optimized before a new one is built.

For each report:

1. Confirm its exact filter/detail contract.
2. Build the missing daily/monthly/performance projection, not just a generic total table.
3. Wire its actual API to that projection; an unused aggregate is not optimization.
4. Remove redundant requests/oversized payloads and duplicate browser calculations.
5. Preserve log drilldown, totals, exact membership, period boundaries and modal equivalence.
6. Record remaining expensive paths and any authorized measurements. Do not declare the entire app optimized because one default view is fast.

Deliverable: each report has an explicit optimized read path independent of source reseeding.

### Ongoing product development

- Add the next module/report when requested.
- Extend shared source entities only for real new information; reuse existing resident/stay/facility/coverage IDs.
- Build the report, settle its behavior, then optimize it under the same lifecycle.
- Add new generators and refresh dependencies without invalidating unrelated domains.
- Retire compatibility shims only after their consumers move; do not leave two authoritative schema/calculation implementations.

