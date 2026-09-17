# Backend, API, reporting, and seeding instructions

## 1. Purpose and authority

This document defines how to grow this application without turning each change into a full reseed, a slow report, or an incompatible production schema.

These are durable engineering rules. They do not prescribe a module order, freeze product choices, or assert that the target architecture is already implemented. Dated implementation observations and refactor milestones live in separate planning documents.

Read this file before changing backend structure, models, migrations, report APIs, reporting calculations, seed generators, or ingestion. Follow the user's current instructions and `AGENTS.md`, including the prohibition on unsolicited tests.

For UI work, also read [frontend/STYLE_GUIDE.md](frontend/STYLE_GUIDE.md). It owns shared visual standards and interaction conventions. Report-specific choices belong in report contracts or dated context. Backend optimization must preserve the applicable UI contracts unless changing them is part of the request.

### Applying these instructions as the application evolves

- The user's latest explicit request controls product scope and priority. Earlier choices remain defaults only where the user has not changed them.
- Examples name possible entities or reports; they are not a closed list of permitted work.
- A request to build a new module makes that module current work, even if an older document calls it future, deferred or a placeholder.
- Preserve unrelated behavior during a scoped change, but implement explicitly requested changes without treating the old behavior as a prohibition.
- Distinguish engineering rules, shared design defaults, report contracts, implementation observations, and proposals. A current code limitation is not an architectural requirement; a proposed capability is not an implemented feature.

Companion documents:

- [Report audit](docs/report-schema-audit.md): dated observations of implemented screens, bottlenecks, calculation pitfalls, and open definitions.
- [Proposed shared schema](docs/proposed-shared-schema.md): candidate tables, columns, relationships, and serving structures for review.
- [Backend refactor plan](docs/backend-refactor-plan.md): dated transition milestones, separate from permanent rules.

The schema proposal is not approval to build every table immediately. This document governs the incremental workflow. Its performance roadmap must not prevent prototyping a new report.

## 2. Philosophy

1. **Build incrementally in the order the user chooses.** Any module or report can be started, extended, or optimized independently. Implement the requested scope and its actual dependencies without adding unrelated work.
2. **Get identity and relationships right early.** Residents, census stays, payer coverage, bed history, facilities, and reference values are shared facts, not possessions of a report module.
3. **Design the report before optimizing its read path.** A prototype may query canonical records. Once the report is understood, add the appropriate summaries and serving structures without changing its meaning.
4. **Source records and reporting results are separate.** Regenerating demo people is not an acceptable way to refresh an average or fix a chart.
5. **The seeder is an engineering subsystem.** It requires stable IDs, independent generators, explicit scopes, dependency planning, recovery, versioning, and deterministic outcomes.
6. **Demo and production have the same schema.** Use the same models, migrations, constraints, metric definitions, and reporting transformations. Fake generation and real ingestion are different inputs to the same contract.
7. **A full reset is exceptional and explicit.** Ordinary development should update a reference, a field, a dataset, a facility, a date range, or a derived report.
8. **Optimize the whole request.** Database work, repeated API requests, response size, filter queries, exports, and browser rendering all affect wait time.
9. **Do not promise unmeasured performance.** Identify the required read path, choose indexes and summaries, and report what has actually been measured when measurement is authorized.
10. **Respect operation scope.** Documentation and code edits alone do not authorize data replacement or unrelated runtime operations. Follow the authorization in the active task.

## 3. Target folder structure and ownership

The API and fake-data generator must be sibling packages, not mixed inside a single API application package.

```text
backend/
  api/
    main.py                  # HTTP application composition only
    routes/                  # HTTP parsing, authorization, response dispatch
    schemas/                 # Request/response contracts
    services/                # Report orchestration and application use cases
    queries/                 # Read queries for prototype and optimized reports
    dependencies/            # Authentication, authorization, request context

  seeding/
    cli.py                   # Explicit seed entrypoint
    planner.py               # Pure operation/scope/dependency plan
    runner.py                # Execution, batching, progress, recovery
    registry.py              # Demo generator declarations
    generators/              # Independent fake source generators
    reference_data/          # Demo reference definitions and aliases
    scenarios/               # Versioned generation parameters
    state/                   # Seed manifests, coverage, checkpoints

  domain/
    identities/              # Shared identity contracts
    residents/
    stays/
    coverage/
    facilities/
    metrics/                 # Pure business definitions, period/LOS/classification rules
    contracts/               # Shared typed inputs/results, not HTTP models

  data/
    models/                  # The one canonical set of database table definitions
    migrations/              # Versioned shared schema changes
    repositories/            # Persistence primitives; no fake generation
    writers/                 # Canonical writes shared by generation and ingestion
    db.py                    # Lazy engine/connection setup

  reporting/
    registry.py              # Reporting datasets and their source dependencies
    planner.py               # Dirty scope propagation; independent of the seeder
    projections/             # Stored event logs and current state
    daily/                   # Shared daily aggregates
    monthly/                 # Shared monthly aggregates
    performance/             # Stored comparisons and classifications
    publication/             # Atomic publication, readiness, revision, coverage
    results/                 # Prepared default responses and custom-result cache

  common/
    config.py                # Environment/settings; no import-time DB calls
    time.py                  # Clock/date/timezone contracts
    logging.py

  pyproject.toml             # Explicit runtime vs demo dependency groups

frontend/                    # Presentation, interactions, request state
instructions.md
seed_data.py                 # Optional thin compatibility launcher
run_app.py                   # Local terminal-owned service launcher
```

The package boundaries define ownership; the listed files and domain subpackages illustrate that ownership. Locate the actual implementation before editing it. Create subpackages when there is code to own, and extend them for requested domains. An ETL can live separately and consume the shared source/publication contracts. Neither this tree nor a package refactor is a prerequisite for unrelated feature work.

### Import boundaries

| Area          | Allowed dependencies                                                                     | Must not depend on                                                 |
| ------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `api`       | domain rules, data models/repositories, reporting read/results interfaces, common        | seeding, fake data, generator configuration, source-generating CLI |
| `seeding`   | domain, canonical data writers/models, common, explicit reporting publication interfaces | API routes, FastAPI request handlers, frontend labels              |
| `reporting` | domain, data, common                                                                     | seeding, API handlers, random/demo generators                      |
| `domain`    | Other domain contracts and standard/pure utilities                                       | HTTP framework, database engine, seeding, frontend                 |
| `data`      | Domain types where necessary, SQL/database libraries, common                             | API handlers, seeding, reporting orchestration                     |
| `common`    | Infrastructure libraries and standard library                                            | Feature packages or generation                                     |

- Reference definitions must not be imported from a fake generator by an API. The database/reference contract owns valid payers and types.
- Reporting jobs accept connections, scope, rules, and source data. They must not create fake source records as a side effect.
- The reporting dependency registry belongs to reporting, so any production ingestion can use it without importing the seeder.
- Importing a model, router, registry, or settings module must not connect to the database, reflect tables, migrate, seed, or start a service. Open connections inside explicit operations.
- Package imports must work through the configured package/entrypoints. Avoid permanent scattered `sys.path` hacks or assumptions about the current working directory.
- Separate dependency groups permit deploying the API/shared reporting code without installing or loading demo-generation libraries. Independent microservices are not required to enforce these boundaries.

## 4. Shared schema rules

### 4.1 Canonical identities

- Use stable primary keys and enforced foreign keys. Labels and names are display values, not join keys.
- One resident identity survives readmissions, payer changes, bed moves, and facility transfers.
- A census stay represents an admission episode. Primary payer intervals and bed-assignment intervals reference it separately.
- Payer types, payer identities, and plans are reference entities. A payer name change must not require replacing stays or events.
- A temporary absence and a reserved bed are explicit facts. Do not infer physical presence from an active stay alone.
- Reference mappings preserve source-system identifiers and organization/facility scope. Do not merge people or hospitals solely by matching names.
- Enforce organization ownership in relationships and query scopes; do not permit cross-organization references accidentally.

### 4.2 Historical correctness

- Preserve interval history for coverage, capacity, hierarchy assignment, bed assignment, absence and operational statuses.
- Use start-inclusive/end-exclusive intervals with explicit same-time event ordering. Distinguish date-only data from known timestamps.
- Use facility-local reporting dates and documented cutoffs. Never let browser, database server, and seeder choose different implicit timezones.
- Opening residents may predate the retained history. Preserve their real dates when known; explicitly represent unknown admission dates rather than inventing them at the seed-window start.
- Preserve payer at admission/discharge through interval resolution. Store resolved IDs in read projections so logs can explain their totals.
- Source flags and derived classifications are distinct where rules can differ, such as readmission.
- A missing value or missing day is not zero. Track coverage/completeness and return unavailable when appropriate.
- Renames are reference edits; reclassifications and identity merges are explicit data corrections with dependent reporting refreshes.

### 4.3 Schema evolution

- Use versioned migrations for both demo and production. Seed code does not own DDL or silently create tables.
- Add fields/entities when the requested workflow or report requires them. Put each fact in its owning domain rather than adding unrelated module-specific columns to shared identity records.
- Prefer additive changes, explicit backfills, compatible read transitions, then later cleanup. Do not couple a table rename, business-rule rewrite, and full reseed in one opaque operation.
- Backfills update the relevant columns/rows with provenance. They are not an excuse to regenerate source identities.
- Unapplied migrations must produce an actionable compatibility error; never auto-apply them from an API request or seed run.
- Demo-only tuning belongs in versioned scenario configuration, not clinical source fields. Demo tracking tables can exist unused in production so schemas remain identical.

## 5. Report lifecycle: build first, optimize afterward

Every report has a documented stage:

| Stage     | Expected work                                                        | Acceptable data path                                                                        |
| --------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Prototype | Agree fields, filters, drilldowns, calculations, date semantics      | Bounded, indexed canonical/read-projection queries are acceptable                           |
| Defined   | Behavior and metric definitions understood; record read requirements | Same prototype implementation may continue while optimization is planned                    |
| Optimized | Add summaries, prepared responses, indexes, smaller payloads         | Interactive overviews use published summaries/snapshots; logs use indexed event projections |

Do not claim a prototype is optimized merely because its API response is cached. Do not block UI/report development on building every future aggregate. Prototype and optimized reports may coexist.

This lifecycle applies to reports, not to every application capability. A requested operational workflow, integration or administration feature can introduce its own entities and APIs without first designing a report. It still follows the shared identity, schema, scope and correctness rules.

For each report keep a short contract with:

1. Active tables/charts/modals/tooltips and their fields.
2. Supported periods, entity scopes, filter dimensions, sorting, search and export, as applicable to that report.
3. Metric definitions, distinct-count scope, comparison periods, zeros and incomplete-period behavior.
4. Source entities and the proposed summary grain or projection needed to preserve supported filters and temporal meaning. Daily/monthly grains apply only where the report needs them.
5. Each API's current read path, stage, payload bound, cache key and dependencies.
6. Planned optimization, measured results if available, and any unresolved business definitions.

Reuse calculation services when the same report is opened in different contexts, such as a standalone page and a modal. Different presentation must not silently change metric meaning.

## 6. Seeder operation contract

These are capability requirements, not a claim that a particular CLI already provides them. Verify available commands and scope support against the implementation before giving execution instructions. Document gaps as implementation status, not permanent limits on future work.

### 6.1 Separate operations

| Operation         | Meaning                                                                       | Must not do                                                         |
| ----------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Plan/preview      | Describe requested targets, scope, prerequisites, writes and dirty dependents | Write data or require DB access for an offline plan                 |
| Inspect           | Explicit read-only check of source/schema/coverage/checkpoints                | Change data                                                         |
| Update/catch-up   | Fill missing dates and apply explicitly requested source changes              | Regenerate completed unrelated history                              |
| Populate          | Generate missing source history within the shared window                      | Delete existing retained history                                    |
| Scoped rebuild    | Replace only the specified generator-owned dataset/scope                      | Silently replace all ancestors or unrelated datasets                |
| Backfill          | Fill/correct a named field or representation on existing rows                 | Change entity identities or unrelated attributes                    |
| Reporting refresh | Rebuild selected projections/summaries from existing canonical sources        | Call any fake source generator                                      |
| Resume            | Continue a recorded compatible incomplete run                                 | Skip uncommitted work or mix generator versions silently            |
| Full reset        | Explicitly replace the requested demo database/dataset population             | Run implicitly because code, a reference label, or a report changed |

Schema migration is a separate operation from all of these.

### 6.2 Required scope controls

Design the CLI and planner to accept:

- Dataset(s), organization, facility IDs, date range and explicit as-of date.
- Entity IDs or a named backfill for narrow changes where applicable.
- Generator/scenario version and a deterministic scenario key.
- Preview mode, read-only inspection, resume/run ID, batch size and bounded concurrency.

An unsupported scope must fail with an explanation or produce a precise expanded dependency plan. It must never quietly turn into a global rebuild.

### 6.3 Stable generation

- Generate identities from stable source/scenario identity, independently of mutable labels, list position and generator version.
- Use independently keyed randomness per entity, date and attribute family. Adding a payer must not shift an unrelated random sequence and rename residents or move their admission dates.
- Maintain separate versions for reference definitions, resident identity generation, stay simulation, coverage, beds, statuses and reporting rules.
- A generator code change does not automatically mean old data is invalid. Declare whether it is compatible, future-only, requires a targeted backfill, or requires replacing specified generator-owned history.
- Adding a payer definition does not redistribute historical payers. Assigning that payer to existing demo histories is a distinct scoped request.
- Each generator declares which source rows/fields it owns. It cannot delete another generator's records or overwrite real imported/manual data accidentally.
- Re-running a completed operation with unchanged inputs is idempotent: no duplicate records and no changing results.

### 6.4 History and incremental state

- Every date-based generator uses the shared SeedWindow: first day of the month 36 months before as-of through as-of inclusive, preserving 36 complete months plus current MTD.
- Scoped repairs operate inside retained history without redefining or trimming it. Shorter requested windows do not authorize deletion of older records.
- Coverage records distinguish known zero-activity dates from unprocessed dates.
- Daily catch-up finds missing/incomplete dates, not merely yesterday or the last positive event.
- Stateful generators maintain resumable boundary state per relevant facility/entity. An edit inside a stay may require starting before the requested day and propagating forward until state is consistent; the preview must explain this.
- Avoid replaying the entire 36-month simulation for every daily update. Persist compatible checkpoints; explicitly rebuild affected boundary state if an old change invalidates it.
- Report-window retention and raw-source retention are separate. No automatic purge merely because the rolling display window advanced.

### 6.5 Dependency planning

Declare dependencies at the dataset and changed-field/scope level. Dependencies identify what must be consistent, not a command to regenerate every ancestor.

Examples:

| Requested change                      | Allowed consequences                                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Payer label rename                    | Reference row, affected search/display projections/caches                                                    |
| New payer type/plan                   | Reference row; only subsequently requested coverage generation uses it                                       |
| Coverage update for selected stays    | Those intervals, payer-at-event projections, payer movements/census, affected daily/monthly/hospital outputs |
| Facility name change                  | Reference row and labels/search/cache; no new residents or admissions                                        |
| New facility                          | Its reference/hierarchy/bed data and explicitly requested population/history                                 |
| Bed move or hold correction           | Bed/absence/reservation projection and affected census/availability metrics; admission dates unchanged       |
| LOS calculation change                | Affected log/summary backfill under a new definition version; source stays retained                          |
| New report                            | New queries or reporting datasets over existing source data                                                  |
| Hospital performance threshold change | Performance snapshots/results; existing monthly counts retained                                              |
| Missing daily runs                    | Missing source dates, continuing state and affected outputs through as-of                                    |

An ancestor may need verification, not mutation. Reporting-only refresh must not import the generator registry at all.

### 6.6 Batches, recovery and production protection

- Require an explicit demo target for fake generation; refuse production targets using environment and database identity checks, not a name guess. The shared schema remains the same.
- Use bounded batches and scoped locks. Do not hold a global multi-hour transaction/table lock as the default long-term design.
- Record run ID, plan, scope, versions, stages, attempted/completed batches, checkpoints, errors and timing. Logs must not expose credentials or resident-sensitive data unnecessarily.
- Checkpoint advancement and each batch's durable writes must agree. A killed process is recoverable; it is not marked complete.
- Separate source loading from summary building for bulk pipelines. Commit source batches with durable checkpoints, record affected report scopes, then build summaries across those scopes after source loading completes. Support source-only execution and reporting-only retries. Do not require every facility source batch to rebuild reporting.
- Stage replacement outputs and publish coherently. Reports must not mix incomplete source loads with older summaries: use versioned serving snapshots or an explicit unavailable state until publication completes.
- Use the shared data writer for bulk persistence, conflict handling, changed-only updates and returned IDs. Generators own scenario relationships and scoped replacement policy, not private implementations of bulk SQL/COPY.
- On retries, uniquely identify operations/events so a duplicate ingestion or seed batch cannot double counts.
- Continue serving the last complete reporting publication while new output is prepared. Do not make the application unavailable merely because a background refresh is running.
- Dirty-field dependencies must include corrections and deletions, not just inserts.

## 7. Shared reporting pipeline

The seeder and production ingestion write canonical records through shared contracts. Both invoke the same reporting refresh/publication mechanism for affected reporting dependencies. Only fake generation lives in `seeding`.

The flow below illustrates common reporting dependencies. Build only the nodes required by defined consumers; a domain does not need daily, monthly and performance tables merely because other domains use them.

```text
canonical source changes
  -> affected event/current-state projections
  -> affected daily measures and exact memberships
  -> affected monthly measures and hierarchy rollups
  -> performance snapshots and prepared default results
  -> coherent publication
```

### 7.1 Precompute the costly work

For each optimized report, identify expensive joins, history reconstruction, lookbacks, comparisons, classifications and aggregations. Move the work needed by its interaction contract into refreshable projections, summaries or prepared results before page load. Retain enough detail for supported filters and drilldowns.

Choose period lengths, classification thresholds, dimensions and granularity from that report's versioned contract. A hospital comparison window, census cutoff or trend limit is not a default for unrelated reports. Examples for the reports reviewed in September 2026 are in the [report audit](docs/report-schema-audit.md).

A normal SQL view does not precompute its query. Store/index a projection or aggregate when the expensive query must leave the request path.

### 7.2 Preserve the information needed for exact answers

- Retain payer type and plan separately. Preserve combined filter dimensions needed by the report (for example payer + source type + readmission measures).
- Store sums and denominator counts as well as prepared averages. Never average facility averages or occupancy percentages.
- Distinct resident/hospital/facility counts require exact memberships or an exact bounded query, not sums of daily distinct counts.
- Count a payer transition once even if both old and new types are selected. Specify whether in/out means gross payer movements or crossings of the selected cohort boundary.
- Compute a group's maximum/minimum after summing that group's daily/monthly series. Do not add independent facility maxima.
- Census uses first open and last close across a period; never sum daily census to label it a period census. Census-day totals are separate average inputs.
- Preserve all tied extrema dates and known zero-activity days/months.
- Use approved performance thresholds and completeness rules from one versioned definition. Frontend and backend must not implement conflicting classifiers.
- A new arbitrary selection may require small summary arithmetic. Do not promise a permanent row for every possible date, payer and facility combination.

### 7.3 Published versions and caches

- Source watermark, rules version, coverage and readiness accompany a publication.
- A page and its detail requests use compatible published data. Pass publication IDs; retain required old versions briefly or request a coherent refresh when no longer available.
- Cache keys include organization, effective permission scope, publication, rules, business date, canonical filter IDs, sort and pagination where relevant.
- Prewarm a bounded set of standard/default results. Cache custom results after bounded summary queries. Do not materialize the power set of facility or payer selections.
- A failed refresh leaves the last complete publication usable and visibly dated. Do not display missing/current-unavailable as zero.
- Update ongoing LOS/current snapshots and relative-date caches at the relevant date rollover even if there are no source events.
- Freshness follows source ingestion cadence. A one-minute browser poll cannot make a daily source real-time.

## 8. API rules

- Routes are thin: validate input, establish authorization/scope, call a service, serialize a typed response. No inline fake generation, DDL, migration, or reporting rebuild.
- Services express report use cases. Queries own read SQL. Domain code owns metric meaning. Keep transaction ownership explicit.
- Preserve a stable response contract when swapping a prototype query for an aggregate. Version deliberately when required; do not use a cache to disguise mismatched meanings.
- Use IDs in requests and relationships. Return labels for display. Validate fields, dates, ranges, sort columns, filter combinations and page limits.
- Enforce authorized facilities before aggregation, distinct counts, filter options, totals, caching and exports.
- For optimized overviews, avoid raw resident-history/event scans. Read prepared results, snapshots or compact summaries. Logs legitimately query indexed event projections.
- Avoid requests that repeat the same scan for each chart or hierarchy level. Return related overview datasets together where practical, while keeping heavy detail lazy.
- Return series at the granularity and bounded point count defined by the report contract. Fetch finer detail on demand. Do not impose one report's grouping policy on every chart.
- Main lists return the fields needed to render them; fetch entity history and detailed relationships when opened.
- Paginate event logs, use stable ID tiebreakers, and plan for deep pagination. Separate expensive count queries and filter searches from simple next-page reads where the UI permits it.
- Reference options use reference tables. Contextual facets use summaries/indexed projections; high-cardinality names are searched/paged on demand.
- Preserve cross-filter semantics: a payer distribution may ignore its own selected payer while respecting source/location filters. Treat each chart's filter contract explicitly.
- Bound timeouts and cancellation; avoid connection-pool exhaustion from nested handlers opening connections. Call services, not HTTP route functions from other route functions.
- Return clear unavailable/stale/partial/error states with publication metadata. Diagnose failures at their source; do not change unrelated configuration to mask a backend error.
- Small exports can stream; large exports use bounded jobs. Export filters, totals, authorization and publication must match the visible report.
- Keep expensive business aggregation and classification out of the browser. Prototype UI arithmetic may be temporary; migrate it without changing the definitions during optimization.

## 9. Performance and maintainability

Record latency, payload, refresh and resource budgets for the applicable workflow and deployment. Measure time to useful content, including network and frontend costs, rather than SQL time alone. The [report audit](docs/report-schema-audit.md#7-performance-budgets-to-approve-and-later-measure) contains initial proposed numbers for its reviewed reports; those are neither measured results nor universal budgets for future workloads.

- Document expected organizations, facilities, residents, events, retained history and concurrency before claiming production readiness.
- Check cold and warm behavior; first-request performance matters. Measurement is performed only when requested/authorized, not by automatically running tests during implementation.
- Design indexes for real predicates and ordering, not every possible column combination. Monthly partitioning is a scale decision for large history tables, not a default for small dimensions.
- Budget aggregate size and refresh duration. Precomputing everything imaginable can make ingestion slow and expensive.
- Include update/delete cost, migration compatibility, bounded cache retention and publication cleanup in optimization.
- Avoid speculative abstractions. A reusable contract with two real callers is preferable to a large framework for modules not yet designed.

## 10. Planning and handoff rules

- The user chooses the next module, feature or report. There is no fixed module order.
- Apply the report lifecycle independently to each report. Starting one module does not require finishing or optimizing another unless there is an actual technical dependency.
- Implement actual technical prerequisites within the authorized task scope. Explain a concrete dependency when it affects the work; do not infer prerequisites from an old roadmap or list order.
- Keep durable architecture/workflow rules here. Put dated priorities, observed implementation state, open decisions and transition checklists in separate planning/status documents.
- The [backend refactor plan](docs/backend-refactor-plan.md), [report audit](docs/report-schema-audit.md), and [schema proposal](docs/proposed-shared-schema.md) are contextual documents. They are not standing assignments or permanent restrictions on what can be built.
- Verify dated claims against the current repository. A report described as a placeholder in an old audit may now be implemented.
- When the user changes direction, work on the requested scope and update relevant planning context. Do not ask the user to reconfirm a clear request simply because it differs from an older plan.
- When recording progress, state what was implemented, what was applied to the database, what remains proposed and the next relevant steps. Do not label intended architecture as existing behavior.

### Maintaining instructions without freezing the product

- Put reusable ownership, correctness, scope and development rules in the instruction files. Put report fields, default periods, thresholds and layouts in that report's contract or dated product context.
- Put generator population sizes, distributions and fake-data assumptions in scenario configuration and its documentation. They do not constrain production data or all future datasets.
- Date implementation observations and proposals; identify what was inspected or measured. Do not turn "currently unsupported" into "must never support," or a list of existing modules into a permitted-module list.
- When behavior changes, update its owning contract and remove or mark superseded guidance. A disclaimer at the top does not fix contradictory instructions elsewhere.
- Before adding a rule, check that it would still make sense with a different module, report design, scale or development stage. If it applies only to one of those, name that scope explicitly.
- Record material decisions, not every temporary experiment as a permanent prohibition. Do not invent extra approval gates from an old plan; clarify only a relevant unresolved decision that the current request and code cannot settle.

## 11. Completion and operating rules

For a change, report what changed, whether it is source/schema/read-path/UI work, what needs migration/backfill/refresh, and what was actually executed. Distinguish proposed commands from available commands and prepared code from applied database changes.

Before calling work complete, review the applicable rules:

- Source identity/history remains stable outside the requested scope.
- Schema changes are shared by demo/production and owned by migrations.
- No forbidden imports, import-time DB work or generation in API startup.
- Relevant report filters, logs, modals and totals use the same definitions.
- Dirty scopes, retries and publication behavior are explicit.
- Full reseed is not the implicit fix for a normal edit.
- Prototype vs optimized status and unmeasured performance are stated honestly.
- Implementation stays within the requested scope and its actual dependencies.

Do not write, add, modify or run tests unless the user explicitly requests it. Do not run migrations, seeders, data replacement, services or performance exercises merely because code was written. Follow existing session authorization; an explicit instruction to execute a particular operation remains sufficient authorization for that operation.

Local servers and helpers must stay owned by their terminal/launcher and stop when it stops. Do not create hidden persistent services, scheduled seed jobs, or orphan processes as a side effect of development. A future scheduled daily run must be an explicitly configured operation, not something performed by API startup.
