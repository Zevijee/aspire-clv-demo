# UI context snapshot

Recorded September 17, 2026. This preserves report-specific choices observed or requested at that time. It is historical context, not a set of instructions, a complete inventory, or a restriction on future work. Verify factual claims against current code. The latest request determines what changes; an older choice does not require reconfirmation.

Shared UI engineering and design conventions belong in [STYLE_GUIDE.md](../frontend/STYLE_GUIDE.md). A report's choices below do not establish defaults for other reports or modules.

## Navigation and filtering at the snapshot

- The main URL opened a neutral starting page. Direct report links expanded the corresponding module rather than always expanding ADT.
- Side-filter drawers were hidden by `ReportLayout`, while the shared drawer implementation remained available.
- Header dropdown summaries used `1 selected` or `N selected`, including when only one item was selected. Standalone report Clear actions appeared only when a relevant filter was applied.
- Date-range reports used a 30-day default. Monthly ADT used a month picker with 24 selected months including the current month to date. Live Census and Referring Hospitals had no date picker.
- Location drilldowns ran through State, Portfolio, Region, Facility, and selected-facility detail where supported.

## Table and chart choices at the snapshot

- Location was the first column in summary tables. Resident was first and pinned in ADT logs. Net change was the first metric after location.
- Census labels were **Open census** and **Close census**.
- Net-change values and bars were signed, with positive values green, negative values red, and zero neutral. Admission trend bars were green and discharge bars red. The active bar had a gray hover band.
- Net-change tooltips had separators between dates, census, and net change, with the interval length in parentheses. Date-range trends used equal-day grouping with at most 60 bars, preferably at least 15 where possible. Monthly reports used calendar months.
- Payer-change donuts used three columns on wide screens, reducing to two and then one. Their legends stacked according to each card's available width.
- Logs/day-over-day tabs, payer charts, some average columns, and some selection checkboxes had been removed from particular reports. These removals were local product decisions rather than prohibitions on those capabilities.

## Detail views at the snapshot

- Full-screen-style detail modals used an outer gutter, report-canvas background, close control, and constrained content height. Tables retained their titles and toolbars with normal header density and internal scrolling.
- Monthly ADT overview modals matched the corresponding standalone report for the selected month, location, and payers, with modal filter state isolated from the parent page.
- Hospital detail placed receiving facilities on the left at 25% and the trend on the right at 75% on wide screens. That split belonged to the hospital composition, not to every modal.

## Maintenance

Record a new dated snapshot when material product context changes; identify superseded choices clearly. Keep standing engineering rules in the style guide and verify current behavior from code instead of applying this snapshot as a checklist. The absence of a module or workflow here imposes no limitation on building it.
