import { type ExcelTable } from './reportExcel'

/** What a report on screen adds to its HTML export, beyond the copy of the page:
 * styles, markup and a script, so the file can do some of what the page does --
 * the Staffing Overview's employee windows, for one. */
export type ExportExtra = { css?: string; html?: string; script?: string }

/** Something the page on screen adds to its export, asked at export time. */
export type ExportContributor = () => Promise<ExportExtra | null>

const contributors = new Set<ExportContributor>()

/** Add to every export while the report is on screen; returns the removal, for
 * a component's effect to undo when it leaves the page. */
export function registerReportExport(contributor: ExportContributor) {
  contributors.add(contributor)
  return () => { contributors.delete(contributor) }
}

/** Everything the reports on screen add to an export, together. */
export async function collectExportExtras(): Promise<Required<ExportExtra>> {
  const extras = (await Promise.all([...contributors].map(contributor => contributor()))).filter(Boolean) as ExportExtra[]
  return {
    css: extras.map(extra => extra.css ?? '').join('\n'),
    html: extras.map(extra => extra.html ?? '').join('\n'),
    // Each its own statement: two scripts that each run a function in brackets,
    // run together without one, read as the first calling the second.
    script: extras.map(extra => `${extra.script ?? ''};`).join('\n'),
  }
}

/** A report's own sheets for its Excel export, in place of the tables drawn on
 * the page, asked at export time: a Staffing report's role tables, a Total and
 * one per location shown, each a role table (roleSheets). */
export type ExcelContributor = () => ExcelTable[] | Promise<ExcelTable[]>

const excelContributors = new Set<ExcelContributor>()

/** Give the Excel export these sheets while the report is on screen; returns the
 * removal, for a component's effect to undo when it leaves the page. */
export function registerExcelSheets(contributor: ExcelContributor) {
  excelContributors.add(contributor)
  return () => { excelContributors.delete(contributor) }
}

/** Every sheet the reports on screen add, in the order they registered. */
export async function collectExcelSheets() {
  return (await Promise.all([...excelContributors].map(contributor => contributor()))).flat()
}
