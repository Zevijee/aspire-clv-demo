# Aspire Analytics Frontend Style Guide

## Purpose

This guide is the required visual and interaction standard for every Aspire Analytics frontend change. The product is a professional analytics platform for skilled nursing operations. It must feel trustworthy, calm, efficient, and appropriate for executive, regional, and facility-level users.

Before introducing or modifying a frontend component, page, chart, table, filter, or interaction, use the shared design system. Extend its tokens or supported variants when the requested work needs a new pattern; do not introduce isolated colors, spacing, fonts, or inconsistent controls.

This guide defines shared defaults and engineering contracts, not a fixed set of modules, workflows, or report layouts. A requested design change may evolve those defaults. Keep accessibility, data meaning, and shared ownership intact, and preserve unrelated behavior. Extending the design system within the requested scope does not require separate approval merely because a pattern is new.

## Design Principles

Read this guide through [AGENTS.md](../AGENTS.md). Backend/API and incremental report-development rules live in [instructions.md](../instructions.md). User instructions take precedence. The root README provides setup and navigation; verify dated UI descriptions against current code and the requested change.

1. **Professional before decorative** - Interface elements support decisions and analysis; they do not compete with the data.
2. **Clarity before density** - Present the most relevant information first, with detail available through intentional drill-down.
3. **Consistency earns trust** - Identical controls, statuses, metric formats, and layouts must behave and appear the same everywhere.
4. **Accessible by default** - Keyboard operation, visible focus, semantic HTML, readable contrast, and responsive behavior are mandatory.
5. **Data is the product** - Charts, tables, filters, values, and comparisons must have clear labels, definitions, and states.

## Shared-component map

Inspect these owners before adding another implementation. Paths and component names are implementation pointers, not permanent package boundaries or a complete inventory. Verify the current owner and public interface in code, especially after refactors, and update this map when an owner moves.

| UI need | Existing owner |
| --- | --- |
| Report shell, title, header filters, body scrolling | `src/shared/components/layout/ReportLayout.tsx` |
| Report tabs | `src/shared/components/layout/ReportTabs.tsx` |
| Tables, sorting, search, export, column filters, pinned columns | `src/shared/components/Table.tsx` |
| Hierarchical tables with default totals | `src/shared/components/DrilldownTable.tsx` |
| Breadcrumbs and custom location-view context | `src/shared/components/DrilldownNavigation.tsx` |
| Header filter placement | `src/shared/components/filters/ReportFilters.tsx` |
| Standard multi-select dropdown | `FilterDropdown.tsx`, composing `MultiSelectFilterOptions.tsx` or `FilterValuePicker.tsx` in the shared filters directory |
| Date/month selection | `ReportDateRangeFilter.tsx`, `ReportMonthRangeFilter.tsx` in the shared filters directory |
| Side-filter drawer, when enabled | `src/shared/components/filters/TabFilterBar.tsx` |
| KPI cards and explanations | `src/shared/components/Kpis.tsx`, `InfoDisclosure.tsx` |
| Loading, empty and retry presentation | `src/shared/components/DataState.tsx` |
| Charts | `src/shared/components/charts/` including `LineChart` with bar variant, `DailyChangeChart`, `DonutChart`, rankings and diverging charts |
| Equal-day trend grouping | `src/shared/utils/trendPeriods.ts` |
| Full-screen detail modal | `src/shared/components/FullScreenModal.tsx` |
| Isolated report state inside modals | `src/shared/components/ReportSearchContext.tsx` |
| Visual tokens / shared CSS | `src/index.css` / `src/App.css` |

Reuse the appropriate shared owners across modules. Features supply data, labels, callbacks and supported options. Improve a shared owner when shared behavior is missing; do not copy it into a feature. Add a shared variant when only some contexts need different behavior, and inspect relevant callers before changing a shared default. New UI needs may justify new components; this map does not limit what can be built.

## Applying the guide to new work

- The user chooses the module, report and design change. Existing patterns are starting points, not a fixed product roadmap.
- Reuse shared visual/interaction infrastructure while allowing the requested report to have different controls, granularity, columns and layouts.
- Report-specific historical choices are recorded in the dated [UI context](../docs/ui-context.md). Verify them against the current task and code. They are not permanent rules for new reports.
- An explicit request to change an existing default or design is sufficient direction; do not ask for reconfirmation because an older document says otherwise.
- Preserve unrelated behavior during a scoped change. When a shared default intentionally changes, assess its callers and update the relevant guidance.

## Shared interaction and detail patterns

- Keep labels visible, align related header controls, and allow widths to fit their contents. Use the shared filter composition rather than a report-specific clone.
- Preserve filter meaning consistently across the table, charts, logs and export. In existing shared multi-select controls an empty selection means unfiltered; a different needed semantic must be explicit in its contract.
- Use shared drilldown navigation with the hierarchy appropriate to the report. Preserve filters while navigating and provide a path back to ancestors.
- Use `DrilldownTable` for its default totals when more than one row is visible; a single row does not need a duplicate total. Supply a correct custom aggregator for ratios, distinct counts and extrema. Do not sum non-additive values.
- Use the shared pinned-column and overflow behavior. Popovers must escape clipping containers without breaking table scrolling.
- Keep sort values numeric for formatted numeric metrics and use an explicit rank for ordered business categories.
- Preserve layout during loading, selection and retry. Do not add incidental font-weight changes or jump the page when values update.
- Use shared KPI/explanation components and omit absent trend icons rather than inventing placeholders.
- Select chart type and time granularity for the report's measure. Reuse shared grouping, tooltip and semantic-color behavior where applicable; do not force every module to have the same trend.
- Reuse shared tables inside modals, retain their title/toolbar, and match normal header density. Constrain modal/table ancestors so internal scrolling actually works; flex/grid ancestors may need bounded height and `min-height: 0`, not just `overflow`.
- Detail views for the same report must use equivalent filters and calculations, with modal state isolated where needed. Load heavy detail on demand.
- Clickable rows support keyboard activation, nested controls must not double-toggle, and closing a modal restores focus.

## Typography

The shared CSS and tokens define current sizing; preserve established component density during unrelated changes. Numeric sizes and CSS examples in this guide describe the shared design defaults. Verify them against their current owners after refactors; do not restore obsolete values merely because an example was not updated. When a requested design changes a default, update its shared owner and the affected documentation together.

Use the system sans-serif font stack for all application content:

```css
font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Preserve shared sans-serif typography. Do not introduce an alternative font for an individual report.

| Use | Size | Weight | Line height |
| --- | ---: | ---: | ---: |
| Page/report title | 24 px | 600 | 1.25 |
| Section title | 20-24 px | 600 | 1.25 |
| Card title | 14-16 px | 600 | 1.35 |
| Body | 14-16 px | 400 | 1.5 |
| Table/filter text | 13-14 px | 400-600 | 1.4 |
| Labels/eyebrows | 11-12 px | 700 | 1.3 |
| KPI value | 24 px | 700 | 1 |

- Use sentence case for titles, labels, and buttons.
- Use tabular numerals for metrics and data tables where supported: `font-variant-numeric: tabular-nums`.
- Avoid all-capital body text. Labels may use uppercase only when they are 12 px or smaller and letter-spaced.

## Color System

Use shared semantic tokens rather than literal colors in components. The palette below is a reference to the shared defaults; verify the current token definitions in code. Add or revise semantic tokens in the shared token owner when needed for the requested design, and update this reference with material changes.

```css
:root {
  --color-canvas: #f5f8fc;
  --color-surface: #ffffff;
  --color-surface-subtle: #eff4fa;
  --color-text: #1d2c3d;
  --color-text-muted: #536579;
  --color-text-subtle: #738397;
  --color-border: #d7e1ed;
  --color-border-strong: #b8c8db;
  --color-primary: #2467a7;
  --color-primary-hover: #194e82;
  --color-primary-subtle: #e7f1fb;
  --color-focus: #216fda;
  --color-success: #27734a;
  --color-success-subtle: #e7f5ec;
  --color-warning: #946200;
  --color-warning-subtle: #fff2d4;
  --color-danger: #ad3030;
  --color-danger-subtle: #fce8e8;
  --color-info: #3d5f91;
  --color-info-subtle: #ebf0f8;
  --color-info-callout-background: #f0f9ff;
  --color-info-callout-border: #a8ddff;
  --color-info-callout-text: #005b8f;
  --color-info-callout-icon: #008bd8;
}
```

- Third-party components must be themed from the same font and color tokens. Do not use their default visual theme alongside application components.
- Keep literal application color values in the shared token owner (currently the `:root` palette in `src/index.css`). Before using a new color, add a semantic token there, then reference the token everywhere else; do not introduce literal color values in feature or component styles. A token-owner refactor must preserve this single source of truth.
- Never communicate status through color alone; pair it with text or an icon that has an accessible label.
- Use blue and navy as the core visual palette. Use `--color-primary` for the primary action and active navigation state only.
- Reserve success, warning, danger, and info colors for their respective semantic statuses.
- Verify text/background combinations meet WCAG AA contrast requirements.

## Spacing and Layout

Use a 4 px base spacing scale only:

| Token | Value | Typical use |
| --- | ---: | --- |
| `--space-1` | 4 px | Tight inline gaps |
| `--space-2` | 8 px | Label/control gaps |
| `--space-3` | 12 px | Compact card padding |
| `--space-4` | 16 px | Standard control and card padding |
| `--space-5` | 20 px | Related section gaps |
| `--space-6` | 24 px | Card and section padding |
| `--space-8` | 32 px | Section separation |
| `--space-10` | 40 px | Page section separation |
| `--space-12` | 48 px | Major page separation |

- Application content uses the available report-panel width and `--layout-report-inline-padding`; do not impose a separate per-report maximum width or padding system.
- Standard report layout uses the shared page header, filter placement, and `--layout-report-section-gap` (currently 16 px).
- Cards use 16-24 px padding, an 8 px radius, a 1 px border, and the shared `--shadow-report-card` when elevation is appropriate. Compact KPI cards use 12 px padding. Avoid excessive shadows.
- Use 8 px border radius for cards and 6 px for controls. Do not use pills except for compact status badges.
- Use CSS grid for dashboard layouts and flexbox for one-dimensional alignment.

## Components

### Report template

Reports use the shared `ReportLayout` component. It owns the report title, short description, padded divider, internally scrollable body, standard content padding, and header filter area. Reports supply content and controls through its supported slots; extend the shared shell when a new report needs a capability instead of duplicating page headers or shell layout rules. Use `ReportDateRangeFilter` for day ranges and `ReportMonthRangeFilter` for month ranges. Choose date, month, fixed-period or no picker according to the report contract. These report conventions do not require non-report workflows to imitate an analytics page.

Use the shared `ReportTabs` component through `ReportLayout` when a report has multiple views. Keep report-specific view content separate while preserving the same header, filters, responsive spacing, and tab treatment. A dense view can opt into `noScroll` so its shared `Table` uses internal scrolling instead of scrolling the report page.

`ReportLayout` also owns the standard report-content spacing: responsive horizontal page insets, a 16 px gap between top-level sections, and a 16 px gap within multi-column report grids. Report-specific views must place top-level sections directly in this shared content stack rather than adding their own page-level gap, and must use the shared grid gap for report-level columns.

All header filters must be placed inside the shared `ReportFilters` component. It establishes the consistent right-side placement, spacing, responsive treatment, label styling, and alignment for every report filter. Filter labels use a semibold weight with the neutral muted-text color.

When a report uses side filters, tab-specific drawers use `TabFilterBar` through the shared `ReportLayout.tabFilters` slot. Its default places the filter button in the floating bottom-right position, without consuming a content row. The button stays anchored while report content scrolls and opens a themed Ant Design drawer from the right. The drawer adapts to the screen width, uses an accessible, vertically scrollable category sidebar and the shared `FilterValuePicker` for consistent counts, search, selected-value review, and bulk actions. Keep visited category panels mounted during the drawer session to retain search and scroll position, and scroll only the option list within each panel, keeping its controls fixed. Keep Apply filters, Cancel, and Clear all in its footer, with an Unapplied changes status when drafts differ. Selections are drafts until Apply filters. Clear all immediately clears applied and draft filters and closes the drawer; Cancel, Escape, the close button, and backdrop dismissal leave the applied filters unchanged. The trigger badge counts applied categories. Keep applied filter state in the report composition and pass the selected values to the tab content. Do not render tab filter bars inside report tables or content stacks, or add per-tab positioning workarounds. Evolve the shared slot or supported variant when a different placement is required.

The shared side-filter drawer's category-navigation default is a vertical sidebar that can accommodate 20 or more filters, with independent scrolling and a narrower sidebar on small screens. Categories support Up/Down arrow keys, Home, and End; each panel keeps its search and scroll position for the current drawer session. Values use plain checkbox rows, available/selected counts, View selected, Select shown / Deselect shown, and Clear selection. Location grouping is independent of checked values; no selection includes all locations. Parent list filters start collapsed, name their active scope, and never remove checked values. Keep category controls fixed and scroll only the option list, with a subtle shadow beneath the selection toolbar. This describes this shared drawer, not a requirement that every future filtering workflow use a sidebar; different navigation belongs in an intentional shared variant or redesign.

### Drill-down navigation

Use the shared `DrilldownNavigation` component for report hierarchies. Pass ordered
`items` with stable IDs, labels, and ancestor `onSelect` callbacks; the final item is
the current location. Optionally pass `level` with `current`, `total`, and `label`.
The component owns breadcrumb separators, styling, responsive wrapping, current-location
semantics, and focus restoration when the path changes. Features own their hierarchy
state and data filtering; do not duplicate the breadcrumb markup or override its styles.

### KPI cards

Use the shared `Kpis` component in the report content stack. It owns card
dimensions, typography, spacing, trend alignment, loading/error presentation, and
responsive behavior. Features supply metric data, request state, and supported
options. Its default is a compact horizontal row with horizontal scrolling at
narrow widths; dashboard grid breakpoints do not apply to that strip. Avoid
feature-specific wrappers, descendant CSS overrides, inline styles, or duplicate
KPI markup that bypasses the shared owner. When a context needs a different
layout or density, add an explicit shared variant. Change the default only
intentionally, after reviewing affected callers; a new variant need not change
every existing report.

### Metric explanations

Use the shared `InfoDisclosure` component for inline explanations of KPIs, formulas, comparisons, and exclusions. Supply a descriptive visible `label` and concise explanation content as children. By default it renders an information callout; use `collapsible` and `defaultOpen={false}` for an initially collapsed explanation. The callout is styled with a small info icon, bold title, pale blue background, thin blue border, and 8 px corners. Use the `--color-info-callout-*` tokens and bold metric names within short flowing paragraphs. Keep the content readable at narrow widths and essential metric labels visible on their cards.

### Buttons

- Every button has a clear action-oriented label.
- Use one primary button per action area. Secondary actions use an outlined or subtle style.
- Prefer comfortable interactive targets. Compact header filters use the established 32 px control height; preserve visible focus and keyboard access.
- Disabled states must remain legible and must not be used as a substitute for validation feedback.

### Inputs and filters

- Labels remain visible; placeholders do not replace labels.
- Reuse the existing shared control sizes. Compact header filters align to the 32 px date picker; do not increase their height independently.
- Group report filters in a dedicated filter bar with Apply and Reset behavior only when filtering is not immediate.
- Date ranges must state the selected granularity and inclusive boundaries.

### Tables

- Use `stickyFirstColumn` to pin a table's first column when horizontal overflow
  requires it. Pinning and its highlight are conditional on actual overflow. The shared Table owns the
  horizontal scrollbar beneath only the moving columns, measures the pinned width,
  and synchronizes wheel and scrollbar movement. Highlight pinned cells with
  `--color-table-pinned-background` (#e0eaf6), using `--color-table-pinned-hover`
  (#d3e1f2) on row hover so it remains distinct from the rest of the row.
  Keep the pinned column free of a
  vertical divider; do not add feature-specific scrollbars or borders.

- Server-side numeric column filters use the shared equals, greater-than, less-than,
  and between controls. Register numeric columns in the backend source's `numeric_keys`;
  the shared query encodes the operator and operands as one JSON array string, preserving
  operand order through multi-select normalization. Apply conditions
  to the full dataset, export, and cascading options; never validate matches from one page.

- Columns may supply `exportValue` when a status must be retained in CSV text (for example,
  an ongoing LOS). Keep `value` numeric when numeric sorting is needed.
- Tables with a server CSV endpoint can supply `onExport` to download the complete
  filtered result. The shared table owns the busy/error state; ordinary tables
  continue to use local CSV export or `getExportRows`.

- Enable the shared `Table` component's optional `searchable` prop when the table's workflow needs search. Its standard toolbar places a labeled search field beside Export to CSV. Search combines with existing column filters. Server-paginated tables must forward `TableQuery.search` through `onQueryChange` to their API, reset pagination when the query changes, and return a total count for all matching records. Choose search and export capabilities according to the report contract, not a fixed list of reports.
- Left-align text and right-align numeric values.
- Comparison columns must declare `change: { favorable: 'increase' | 'decrease' }` on
  their shared `TableColumn`. Use `favorable: 'neutral'` when neither direction is inherently
  favorable, such as payer-change volume. The shared Table owns signed number formatting and uses
  `--color-table-change-favorable` (green) / `--color-table-change-adverse` (red) for both
  body and total rows; zero and unavailable values stay neutral. Reports must not set
  comparison colors or duplicate signed-number renderers. A custom label can use `format`
  with `change.value` supplying its numeric delta; the Table still owns its color.
- Column filter dependencies belong to the shared `Table`: options respect search and
  every other active column filter, while excluding their own selection to allow multi-select.
  Local tables calculate this from all rows. Server-side tables must provide `filterSource`
  (source ID and date range, plus an optional `endpoint`); the shared table owns
  loading, cancellation, error, and Retry states. Feature APIs supply their own
  endpoint; legacy callers default to `/api/v1/table-filter-options/{source}`.
  Do not supply report-specific option lists or calculate server options from a single page.
  Keep allowed column mappings and predicates with the owning backend feature,
  shared by its page, filter-options, and export queries. Do not place runtime API
  code in seeding.
  Preserve request cancellation, cascading, and stale-response behavior. Do not write or run tests unless explicitly requested, per `AGENTS.md`.
- Use tabular numerals for numeric columns.
- Keep headers visible when feasible for long, scrollable data.
- Support empty, loading, and error states.
- Use horizontal scrolling rather than compressing critical columns on small screens.
- Use the shared `Table` component for report data tables. It provides consistent card structure, semantic table markup, responsive horizontal scrolling, accessible sortable columns, clickable multi-select filter icons beside enabled headers, and optional CSV export. Filter menus show search first, then Select all and Clear actions; during search, Select matches adds only matching options and preserves selections outside the search. Values start unchecked, and an empty selection leaves the column unfiltered. Use `internalScroll` for a fixed-height scroll body with sticky column headers.

### Charts

- Use the shared `DonutChart` and `report-chart-grid` with their standard layout and styling.
  Donut cards use their own available width to move the legend below the chart when
  the content width is 560 px or less, including in desktop grids. Wider cards keep
  the legend beside the donut. Preserve the same content height across loading states.
  Set `valueLabel` to the report's measure for accessible table headers. Use
  `centerMode="total"` when the total should remain in the center during hover.

- Every chart has a descriptive title, measure/unit, time range, and a text/table alternative where practical.
- Use the actual series/semantic tokens in `src/index.css`; do not hardcode a universal series color. Preserve report-specific choices unless the user requests a change; dated examples are in the UI context document.
- Avoid 3D charts, decorative gradients, and rainbow palettes.
- Do not rely on hover tooltips as the only way to access critical values.

## Interaction and State

Every data-driven view must handle all four states explicitly:

1. **Loading** - render the full report composition immediately, including every card,
   chart frame, title, table header, and pagination area. Use the shared `DataState`
   animated indicator through `Kpis`, chart, and `Table` loading props, with one indicator
   per KPI card, chart, or table. Reserve the same dimensions in every state; never
   replace a report or section with a loading paragraph. Independent requests must
   start together and fill their own sections as they finish. Apply this on initial
   load and when dates, filters, sorting, or pagination change. Respect reduced motion.
2. **Success** - show data, applied filters, and relevant freshness/period context.
3. **Empty** - state why no data matches and provide a clear next action when possible.
4. **Error** - explain that data could not load and provide a retry action inside the
   existing section frame; do not collapse its layout or silently hide failures.

- Keyboard focus must be clearly visible using `--color-focus`.
- Use native buttons, links, inputs, and semantic landmarks whenever possible.
- Navigation items must expose their current/expanded state to assistive technology.
- Confirm destructive actions and give users clear outcome feedback.

## Responsive Behavior

- Support widths from 320 px upward.
- Grids collapse according to their supported shared variant and available width; do not apply one report's column count to every chart grid.
- Navigation becomes a managed drawer on narrow screens.
- Tables may scroll horizontally; filters stack vertically as needed.
- Never require hover to reveal an essential action or meaning.

## Content and Data Formatting

- Use clear business language; avoid unexplained acronyms. Define SNF-specific measures near first use.
- Format counts with separators (`1,250`), percentages to one decimal when useful (`87.4%`), and currency with appropriate units (`$1.2M`).
- Display missing or unavailable values as `—`, not `0`.
- Show favorable/unfavorable performance direction in context; not every increase is positive.

## Implementation Checklist

Before considering a frontend change complete, verify:

- [ ] It uses the tokens, typography, spacing, and component conventions in this guide.
- [ ] It is responsive and keyboard accessible.
- [ ] Loading, empty, and error states are intentional.
- [ ] Text, labels, and metric definitions are clear.
- [ ] It builds and passes the existing frontend lint command.
- [ ] No temporary, placeholder, or debug data is exposed in the production interface.

## Frontend Architecture

Use a feature-based architecture for all application code:

```text
src/
|- app/                       # Application composition, global routing, and shell
|- features/
|  |- <feature>/              # Feature pages, API client, types, and components
|  `- navigation/             # Cross-feature report catalog used by the sidebar
`- shared/
   |- components/             # Reusable, feature-agnostic interface components
   `- types/                  # Shared domain types
```

- A feature owns its report pages, API requests, local types and report-specific components. Add or change tests only when explicitly requested.
- Shared UI components must be feature-agnostic. Keep feature-specific business rules in their owning feature; use shared domain types or helpers only when their contract is genuinely shared.
- The `app` layer composes features and owns global concerns such as routing and the application shell.
- Do not create a generic top-level `components` folder for new code. Put a component in its feature unless multiple features use it, in which case put it in `shared/components`.

