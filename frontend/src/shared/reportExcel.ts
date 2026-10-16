import { isValidElement, type ReactNode } from 'react'
import { type TableColumn, type TableSections } from './components/Table'
import { tableChange } from './utils/tableChange'
import { excelChartOf, type ExcelChart } from './excelCharts'

/** The report as it is on screen, as an Excel workbook: one sheet for the view, its tables one under another, its
 * title and the report's range above it, the header row frozen, figures as
 * numbers in their own format ($, %, decimals, sign) so they sum and sort in
 * Excel, a figure's share after it in the same cell. Read from the page's
 * tables, so it holds what they show -- a paged table, the page shown -- unless
 * the report gives its own sheets (registerExcelSheets, tableToExcel), with rows
 * that fold open under a row, as a role's employees under it. The page's charts
 * (useExcelChart) follow the table above them on the page as Excel charts, laid
 * out as the page lays them out, drawn from their figures on a hidden sheet.
 * Written as a real .xlsx (zipped XML) with no library. */

type Cell = { value: string | number | null; style: number }
type Sheet = {
  name: string; rows: Cell[][]; widths: number[]; frozenRows: number; merges: string[]
  /** A row's height in points where it is not the default: a wrapped header value. */
  heights?: (number | undefined)[]
  /** Each row's outline: folded under the row above it (1), or holding such rows. */
  outline: { level: 0 | 1; folds: boolean }[]
  charts: PlacedChart[]
  /** A sheet the charts read their figures from, kept out of view. */
  hidden?: boolean
}

const MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const RELATIONSHIPS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
const DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const SHEET_DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'

// --- Styles -----------------------------------------------------------------

// Regular, bold, title, muted, a header label (bold, muted, small) and a header
// value (small, in the text colour).
type Font = 0 | 1 | 2 | 3 | 4 | 5
type Fill = 0 | 2 // none, the header's
type Style = { format: string; font: Font; fill: Fill; indent: number; wrap: boolean }

// Excel takes some 200 to 250 custom number formats in a workbook, and past that
// repairs the file by discarding the rest: 379 did. A figure's share in its cell
// is a format of its own, so they stop short of it, and any past it are text.
const FORMAT_LIMIT = 180

/** Each distinct look a cell takes, numbered as styles.xml lists them; the
 * first is Excel's default. */
class Styles {
  private readonly styles: Style[] = [{ format: 'General', font: 0, fill: 0, indent: 0, wrap: false }]
  private readonly keys = new Map<string, number>([['General|0|0|0|false', 0]])
  private readonly formats = new Set<string>()

  /** Whether a cell can take this number format: one already used, or room for
   * another under Excel's limit (FORMAT_LIMIT). */
  fits(format: string) {
    return this.formats.has(format) || this.formats.size < FORMAT_LIMIT
  }

  get(format = 'General', font: Font = 0, fill: Fill = 0, indent = 0, wrap = false) {
    const key = `${format}|${font}|${fill}|${indent}|${wrap}`
    let index = this.keys.get(key)
    if (index === undefined) {
      index = this.styles.push({ format, font, fill, indent, wrap }) - 1
      this.keys.set(key, index)
      if (format !== 'General') this.formats.add(format)
    }
    return index
  }

  xml() {
    const formats = [...new Set(this.styles.map(style => style.format).filter(format => format !== 'General'))]
    const formatId = (format: string) => format === 'General' ? 0 : 164 + formats.indexOf(format)
    // The page's own text colours, so the header reads as the report does.
    const muted = `FF${excelColor('var(--color-text-muted)', '536579')}`
    const text = `FF${excelColor('var(--color-text)', '1D2C3D')}`
    const alignment = (style: Style) => style.indent || style.wrap
      ? ` applyAlignment="1"><alignment${style.indent ? ` indent="${style.indent}"` : ''}`
        + `${style.wrap ? ' wrapText="1" vertical="top"' : ''}/></xf>` : '/>'
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="${MAIN}">`
      + `<numFmts count="${formats.length}">${formats.map((format, index) =>
        `<numFmt numFmtId="${164 + index}" formatCode="${escape(format)}"/>`).join('')}</numFmts>`
      + '<fonts count="6"><font><sz val="11"/><name val="Calibri"/></font>'
      + '<font><b/><sz val="11"/><name val="Calibri"/></font>'
      + `<font><b/><sz val="14"/><color rgb="${text}"/><name val="Calibri"/></font>`
      + `<font><sz val="10"/><color rgb="${muted}"/><name val="Calibri"/></font>`
      + `<font><b/><sz val="10"/><color rgb="${muted}"/><name val="Calibri"/></font>`
      + `<font><sz val="10"/><color rgb="${text}"/><name val="Calibri"/></font></fonts>`
      + '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
      + '<fill><patternFill patternType="solid"><fgColor rgb="FFEEF2F7"/><bgColor indexed="64"/></patternFill></fill></fills>'
      + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
      + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
      + `<cellXfs count="${this.styles.length}">${this.styles.map(style =>
        `<xf numFmtId="${formatId(style.format)}" fontId="${style.font}" fillId="${style.fill}" borderId="0" xfId="0"`
        + ' applyNumberFormat="1" applyFont="1" applyFill="1"' + alignment(style)).join('')}</cellXfs>`
      + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
  }
}

// --- Tables -------------------------------------------------------------------

const clean = (text: string | null | undefined) => (text ?? '').replace(/\s+/g, ' ').trim()

/** A cell's own text: without the parts marked to stand apart (data-export-column),
 * such as a figure's share beside it, which goes after it in brackets. */
function cellText(cell: Element) {
  const copy = cell.cloneNode(true) as Element
  copy.querySelectorAll('[data-export-column], svg').forEach(part => part.remove())
  return clean(copy.textContent).replace(/,$/, '')
}

/** A figure as Excel holds it: the number and the format that shows it as the
 * page does -- "$1,234" "$28.15" "7.5%" "+0.09" "−0.04" "1,234.5". Anything else
 * stays text; a dash is an empty cell. */
function figure(text: string): { value: number; format: string } | null | 'empty' {
  if (!text || text === '—' || text === '–' || text === '-') return 'empty'
  const match = text.replace(/−/g, '-').match(/^([+-])?(\$)?(\d{1,3}(?:,\d{3})+|\d+)?(\.\d+)?(%)?$/)
  if (!match || (!match[3] && !match[4])) return null
  const [, sign, dollar, whole, fraction, percent] = match
  let value = Number(`${(whole ?? '0').replace(/,/g, '')}${fraction ?? ''}`)
  if (sign === '-') value = -value
  if (percent) value /= 100
  const decimals = fraction ? fraction.length - 1 : 0
  let format = `${percent ? '0' : '#,##0'}${decimals ? `.${'0'.repeat(decimals)}` : ''}${percent ? '%' : ''}`
  if (dollar) format = `"$"${format}`
  if (sign) format = `+${format};-${format};${format}`
  return { value, format }
}

/** A share to whole percent, as "8%": a cell's share is a number format of its
 * own, and a decimal would need ten times as many (FORMAT_LIMIT). */
function wholePercent(note: string | undefined) {
  const match = note?.match(/^(-?[\d.]+)%$/)
  return match ? `${Math.round(Number(match[1]))}%` : note
}

/** A sheet name Excel accepts: at most 31 characters, none of []:*?/\, and not
 * one already taken. */
function sheetName(title: string, taken: Set<string>) {
  const base = clean(title).replace(/[[\]:*?/\\]/g, ' ').slice(0, 31).trim() || 'Table'
  let name = base
  for (let count = 2; taken.has(name.toLowerCase()); count += 1) {
    const suffix = ` (${count})`
    name = `${base.slice(0, 31 - suffix.length)}${suffix}`
  }
  taken.add(name.toLowerCase())
  return name
}

/** A row of a sheet: its cells as the page shows their text, and after a figure
 * its share, shown in the same cell -- "63.72 (8%)" -- while the cell stays a
 * number. `details` are rows folded under it, opened with Excel's +. */
export type ExcelRow = {
  cells: string[]
  notes?: (string | undefined)[]
  kind?: 'section' | 'member' | 'total'
  details?: ExcelRow[]
}

/** A table for a sheet, however it was read. `name` names the sheet, the title
 * unless given. */
export type ExcelTable = {
  name?: string
  title: string
  columns: { header: string; numeric: boolean; group?: string }[]
  rows: ExcelRow[]
}

/** A table drawn on the page (Table), as it is: its group and header rows, the
 * rows shown, sections and all, and its Total row. */
function domTable(card: Element): ExcelTable | null {
  const table = card.querySelector(':scope > .report-table__scroll table')
  const head = table?.querySelector('thead')
  const headRow = head?.rows[head.rows.length - 1]
  if (!table || !head || !headRow) return null
  const body = [...(table.querySelector('tbody')?.rows ?? [])]
    .filter(row => !row.querySelector('.report-table__state, .report-table__empty'))
  if (!body.length) return null
  // Each column's group, from the group row's spans.
  const groups: string[] = []
  if (head.rows.length > 1) {
    for (const cell of head.rows[0].cells) {
      for (let index = 0; index < (cell.colSpan || 1); index += 1) groups.push(clean(cell.textContent))
    }
  }
  const read = (row: HTMLTableRowElement, kind?: ExcelRow['kind']): ExcelRow => ({
    kind,
    cells: [...row.cells].map(cellText),
    notes: [...row.cells].map(cell => clean(cell.querySelector('[data-export-column]')?.textContent) || undefined),
  })
  return {
    title: clean(card.querySelector('.report-table__title')?.textContent) || 'Table',
    columns: [...headRow.cells].map((cell, index) => ({ header: clean(cell.textContent),
      numeric: cell.classList.contains('report-table__numeric'), group: groups[index] || undefined })),
    rows: [
      ...body.map(row => read(row, row.classList.contains('report-table__row--section') ? 'section'
        : row.classList.contains('report-table__row--in-section') ? 'member' : undefined)),
      ...[...(table.querySelector('tfoot')?.rows ?? [])].map(row => read(row, 'total')),
    ],
  }
}

/** What a cell shows as text, and the parts of it marked to stand apart
 * (data-export-column), from the React a column's format returns. */
function nodeText(node: ReactNode, parts: Record<string, string>): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(child => nodeText(child, parts)).join('')
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode; 'data-export-column'?: string }
    const column = props['data-export-column']
    if (column) {
      parts[column] = clean(nodeText(props.children, {}))
      return ''
    }
    return nodeText(props.children, parts)
  }
  return ''
}

/** A table that is not on the page, from the same columns and rows a Table would
 * draw -- sections, as Table groups them, and a Total row -- for a sheet of its
 * own: a role table for each location of a drilldown, say. `details` gives the
 * rows to fold under a row that is not a section's or the total's, a cell for
 * each of the columns shown. */
export function tableToExcel<Row>({ name, title, columns, rows, sections, footer, details }: {
  name?: string
  title: string
  columns: TableColumn<Row>[]
  rows: Row[]
  sections?: TableSections<Row>
  footer?: Row
  details?: (row: Row, columns: TableColumn<Row>[]) => ExcelRow[]
}): ExcelTable {
  const shown = columns.filter(column => !column.hidden)
  const read = (row: Row, kind?: ExcelRow['kind']): ExcelRow => {
    const cells = shown.map(column => {
      const value = column.value(row)
      const parts: Record<string, string> = {}
      if (column.dataType === 'boolean') return { text: String(value ?? ''), note: undefined }
      const node = column.format ? column.format(value, row)
        : column.change ? tableChange(column.change.value ? column.change.value(row) : value, column.change.favorable).text
          : value
      return { text: clean(nodeText(node, parts)).replace(/,$/, ''), note: Object.values(parts)[0] }
    })
    const folded = kind === 'section' || kind === 'total' ? [] : details?.(row, shown) ?? []
    return { kind, cells: cells.map(cell => cell.text), notes: cells.map(cell => cell.note),
      ...(folded.length ? { details: folded } : {}) }
  }
  // Sections as Table builds them: in order of their first row, each row after it.
  const ordered: ExcelRow[] = []
  const place = (members: Row[], prefix: string[]) => {
    const byName = new Map<string, Row[]>()
    for (const row of members) {
      const section = sections!.getPath(row)[prefix.length]
      if (section !== undefined) byName.set(section, [...(byName.get(section) ?? []), row])
    }
    for (const [section, inside] of byName) {
      const path = [...prefix, section]
      ordered.push(read(sections!.getRow(path, inside), 'section'))
      const deeper = inside.filter(row => sections!.getPath(row).length > path.length)
      if (deeper.length) place(deeper, path)
      inside.filter(row => sections!.getPath(row).length === path.length).forEach(row => ordered.push(read(row, 'member')))
    }
  }
  if (sections) place(rows, [])
  else rows.forEach(row => ordered.push(read(row)))
  if (footer) ordered.push(read(footer, 'total'))
  return { name, title, columns: shown.map(column => ({ header: column.header, numeric: column.numeric === true,
    group: column.group })), rows: ordered }
}

/** One labelled line of a sheet's header: Period, Location, Filters, Exported. */
export type ExcelDetail = { label: string; value: string }

// A header value runs across the table's columns, and at least this far, so a
// narrow table still has room for a long filter list.
const DETAIL_LAST_COLUMN = 5
const DETAIL_LINE_POINTS = 13.5 // a 10 pt line

/** A view as a sheet: its title, the report's module, report and tab, then a
 * line for each detail -- its label in the first column, its value across the
 * rest, wrapped there when long -- then each of its tables in page order, the
 * first under the header and each further one under its own title, with the
 * charts that follow it on the page after it (their figures on the hidden
 * `data` sheet). A table is its group and header rows, then its rows, figures
 * as numbers in the page's format, each row's details folded under it. The
 * header rows are frozen when the sheet has one table; with more, the first
 * table's would stand over the others. */
function sheetFrom(tables: ExcelTable[], charts: ChartOnPage[][], name: string, title: string, heading: string,
  details: ExcelDetail[], styles: Styles, data: Sheet): Sheet {
  const sheet: Sheet = { name, rows: [], widths: [], frozenRows: 0, merges: [], outline: [], charts: [] }
  const { rows, merges } = sheet
  const add = (cells: Cell[], level: 0 | 1 = 0, folds = false) => {
    rows.push(cells)
    sheet.outline.push({ level, folds })
  }
  add([{ value: title, style: styles.get('General', 2) }])
  add([{ value: heading, style: styles.get('General', 4) }])
  const detailEnd = Math.max(...tables.map(table => table.columns.length - 1), DETAIL_LAST_COLUMN)
  const detailRows: { row: number; length: number }[] = []
  for (const { label, value } of details) {
    if (!value) continue
    detailRows.push({ row: rows.length, length: value.length })
    merges.push(`${reference(1, rows.length)}:${reference(detailEnd, rows.length)}`)
    // Both top-aligned (the wrap style), so a label stays beside its value's first line.
    add([{ value: label, style: styles.get('General', 4, 0, 0, true) },
      { value, style: styles.get('General', 5, 0, 0, true) }])
  }

  const header = styles.get('General', 1, 2)
  tables.forEach((table, tableIndex) => {
    add([])
    if (tableIndex > 0) {
      add([])
      add([{ value: table.title, style: styles.get('General', 1) }])
    }
    const top = rows.length
    if (table.columns.some(column => column.group)) {
      const at = rows.length
      add(table.columns.map((column, index) => ({
        value: column.group && column.group !== table.columns[index - 1]?.group ? column.group : null, style: header })))
      // Each group's name across its columns.
      table.columns.forEach((column, index) => {
        if (!column.group || column.group === table.columns[index - 1]?.group) return
        let end = index
        while (table.columns[end + 1]?.group === column.group) end += 1
        if (end > index) merges.push(`${reference(index, at)}:${reference(end, at)}`)
      })
    }
    add(table.columns.map(column => ({ value: column.header, style: header })))
    if (tables.length === 1) sheet.frozenRows = rows.length

    const cells = (row: ExcelRow, indent: number): Cell[] => {
      const font: Font = row.kind === 'section' || row.kind === 'total' ? 1 : 0
      const fill: Fill = row.kind === 'total' ? 2 : 0
      return row.cells.map((text, index) => {
        const note = wholePercent(row.notes?.[index])
        const parsed = table.columns[index]?.numeric ? figure(text) : null
        if (parsed === 'empty') return { value: null, style: styles.get('General', font, fill) }
        // The share as text in the number's format, so the cell keeps its number,
        // while Excel has room for the format; else the cell is text.
        const format = parsed && note ? `${parsed.format}" (${note.replace(/"/g, '')})"` : parsed?.format
        if (parsed && format && styles.fits(format)) return { value: parsed.value, style: styles.get(format, font, fill) }
        return { value: (note ? `${text} (${note})` : text) || null,
          style: styles.get('General', font, fill, index === 0 ? indent : 0) }
      })
    }
    for (const row of table.rows) {
      const indent = row.kind === 'member' ? 1 : 0
      add(cells(row, indent), 0, Boolean(row.details?.length))
      for (const detail of row.details ?? []) add(cells(detail, indent + 1), 1)
    }
    // The group row's names span several columns, so widths start at the header row.
    rows.slice(table.columns.some(column => column.group) ? top + 1 : top).forEach(row => widen(sheet.widths, row))
    addCharts(sheet, data, charts[tableIndex] ?? [], styles)
  })

  const { widths } = sheet
  // Room for the header's labels.
  widths[0] = Math.max(widths[0] ?? 8, 11)
  // Excel does not fit a merged cell's height to its wrapped text: each long
  // value's lines, from the width it runs across. Calibri 10's average
  // character is about three quarters of the 11 pt digit the widths count in:
  // 186 characters filled 140 units' width on one line.
  const heights: (number | undefined)[] = []
  const across = Array.from({ length: detailEnd }, (_, index) => widths[index + 1] ?? 8.43)
    .reduce((total, width) => total + width, 0) * 1.3
  for (const { row, length } of detailRows) {
    const lines = Math.ceil(length / across)
    if (lines > 1) heights[row] = lines * DETAIL_LINE_POINTS + 2
  }
  sheet.heights = heights
  return sheet
}

/** Widen each column to fit this row's cells. */
function widen(widths: number[], row: Cell[]) {
  row.forEach((cell, index) => {
    const shown = typeof cell.value === 'number' ? cell.value.toLocaleString(undefined, { maximumFractionDigits: 2 }).length + 8
      : String(cell.value ?? '').length + 4
    widths[index] = Math.max(widths[index] ?? 8, Math.min(60, shown + 2))
  })
}

// --- Charts -------------------------------------------------------------------

/** A chart placed on a sheet: where it is, in pixels across from the sheet's
 * left edge and by row down, its size, and where its figures are. */
type PlacedChart = {
  chart: ExcelChart
  /** The sheet holding its figures, and their header row there; the data runs
   * from the row below it, one per category. */
  dataSheet: string
  headerRow: number
  /** Each series' number format, and what its page values are multiplied by to
   * hold them as Excel does: a percent shown "7.5%" from 7.5 is 0.075. */
  formats: string[]
  scales: number[]
  row: number
  x: number
  width: number
  height: number
}

/** A chart and where the page draws it, in pixels from the report's top left;
 * null when it is not laid out (hidden). */
type ChartOnPage = { chart: ExcelChart; box: { left: number; top: number; width: number; height: number } | null }

/** A chart's size in pixels when the page gives none. */
function chartSize(chart: ExcelChart) {
  if (chart.kind === 'bar') return { width: 560, height: Math.max(220, Math.min(640, 28 * chart.categories.length + 80)) }
  if (chart.kind === 'doughnut') return { width: 480, height: 300 }
  return { width: 760, height: 320 }
}

const ROW_PIXELS = 20 // defaultRowHeight 15 pt
// The widest the charts are drawn, about a laptop's Excel window: a wider page
// is scaled down to it, keeping its proportions.
const CHARTS_WIDTH = 1100
const CHART_MIN_HEIGHT = 200

/** The charts after a sheet's table, laid out as the page lays them out -- side
 * by side where it puts them side by side, at its proportions. Each Excel chart
 * is drawn from its figures, with their page format, on the hidden data sheet:
 * a chart needs cells to read, and the sheet shows the charts alone. A
 * doughnut's figures add each part's share, as its legend does. */
function addCharts(sheet: Sheet, data: Sheet, charts: ChartOnPage[], styles: Styles) {
  if (!charts.length) return
  const add = (cells: Cell[]) => {
    sheet.rows.push(cells)
    sheet.outline.push({ level: 0, folds: false })
  }
  const put = (cells: Cell[]) => {
    data.rows.push(cells)
    data.outline.push({ level: 0, folds: false })
  }

  // The page's rows of charts: those with the same top sit side by side.
  const laidOut = (box: ChartOnPage['box']): box is NonNullable<ChartOnPage['box']> =>
    box !== null && box.width > 0 && box.height > 0
  const boxes = charts.map(({ box }) => box).filter(laidOut)
  const left = Math.min(...boxes.map(box => box.left))
  const span = Math.max(0, ...boxes.map(box => box.left + box.width - left))
  const scale = span > CHARTS_WIDTH ? CHARTS_WIDTH / span : 1
  const rows: { chart: ExcelChart; x: number; width: number; height: number }[][] = []
  let rowTop: number | null = null
  for (const { chart, box } of charts) {
    if (!laidOut(box)) {
      rows.push([{ chart, x: 0, ...chartSize(chart) }])
      rowTop = null
      continue
    }
    const placed = { chart, x: Math.round((box.left - left) * scale), width: Math.round(box.width * scale),
      height: Math.max(CHART_MIN_HEIGHT, Math.round(box.height * scale)) }
    if (rowTop !== null && Math.abs(box.top - rowTop) < 12) rows[rows.length - 1].push(placed)
    else {
      rows.push([placed])
      rowTop = box.top
    }
  }
  add([])
  const placed: Omit<PlacedChart, 'dataSheet' | 'headerRow' | 'formats' | 'scales'>[] = []
  for (const row of rows) {
    const top = sheet.rows.length
    row.forEach(chart => placed.push({ ...chart, row: top }))
    const tall = Math.ceil(Math.max(...row.map(chart => chart.height)) / ROW_PIXELS)
    for (let index = 0; index <= tall; index += 1) add([])
  }

  const header = styles.get('General', 1, 2)
  for (const chart of placed) {
    const excel = chart.chart
    put([{ value: `${sheet.name} · ${excel.title}`, style: styles.get('General', 1) }])
    const headerRow = data.rows.length
    const doughnut = excel.kind === 'doughnut'
    const headings = [excel.categoryLabel, ...excel.series.map(series => series.name), ...(doughnut ? ['Share'] : [])]
    const headingCells = headings.map(value => ({ value, style: header }))
    put(headingCells)
    widen(data.widths, headingCells)
    // Each series' format from the first value the page shows as a figure.
    const formats: string[] = [], scales: number[] = []
    excel.series.forEach((series, index) => {
      const at = series.values.findIndex((value, point) => value !== 0 && figure(series.texts[point]) !== null)
      const parsed = at < 0 ? null : figure(series.texts[at])
      const usable = parsed && parsed !== 'empty' && styles.fits(parsed.format) ? parsed : null
      formats[index] = usable?.format ?? 'General'
      scales[index] = usable ? usable.value / series.values[at] : 1
    })
    const total = excel.series[0]?.values.reduce((sum, value) => sum + value, 0) ?? 0
    excel.categories.forEach((category, point) => {
      const cells: Cell[] = [{ value: category, style: 0 },
        ...excel.series.map((series, index) => ({ value: series.values[point] * scales[index],
          style: styles.get(formats[index]) }))]
      if (doughnut) cells.push({ value: total ? excel.series[0].values[point] / total : null, style: styles.get('0%') })
      put(cells)
      widen(data.widths, cells)
    })
    put([])
    sheet.charts.push({ ...chart, dataSheet: data.name, headerRow, formats, scales })
  }
}

/** A column's width in pixels, at 100%: Calibri 11's digit is 7. */
const columnPixels = (width: number | undefined) => Math.round((width ?? 8.43) * 7)

/** A colour as Excel takes it, RRGGBB, from a CSS colour or a token's var():
 * the page's own value, so the workbook's charts match it. */
function excelColor(css: string | undefined, fallback = '2467A7') {
  if (!css) return fallback
  const token = css.match(/^var\((--[\w-]+)\)$/)
  const value = token ? getComputedStyle(document.documentElement).getPropertyValue(token[1]).trim() : css
  const context = document.createElement('canvas').getContext('2d')
  if (!context || !value) return fallback
  context.fillStyle = `#${fallback}`
  context.fillStyle = value
  const normal = context.fillStyle
  return /^#[0-9a-f]{6}$/i.test(normal) ? normal.slice(1).toUpperCase() : fallback
}

const fill = (color: string) => `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill>`

function richText(text: string, size: number, bold: boolean) {
  return `<c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="${size}" b="${bold ? 1 : 0}"/></a:pPr>`
    + `<a:r><a:rPr lang="en-US" sz="${size}" b="${bold ? 1 : 0}"/><a:t>${escape(text)}</a:t></a:r></a:p></c:rich>`
}

/** The sheet's name as a formula refers to it: quoted, a quote doubled. */
const sheetReference = (name: string) => `'${name.replace(/'/g, "''")}'`
const absolute = (column: number, row: number) => `$${columnName(column)}$${row + 1}`

/** One chart part (xl/charts/chartN.xml): the chart drawn from its figures'
 * cells, with the values cached so it shows before Excel recalculates. */
function chartXml(placed: PlacedChart, sheetName: string) {
  const { chart, headerRow, formats, scales } = placed
  const sheet = escape(sheetReference(sheetName))
  const first = headerRow + 1, last = headerRow + chart.categories.length
  const categories = `<c:cat><c:strRef><c:f>${sheet}!${absolute(0, first)}:${absolute(0, last)}</c:f>`
    + `<c:strCache><c:ptCount val="${chart.categories.length}"/>${chart.categories.map((category, point) =>
      `<c:pt idx="${point}"><c:v>${escape(category)}</c:v></c:pt>`).join('')}</c:strCache></c:strRef></c:cat>`
  const muted = excelColor('var(--color-text-muted)', '536579')
  const border = excelColor('var(--color-border)', 'D7E1ED')
  const grid = excelColor('var(--color-chart-grid)', 'E5E7EB')
  const palette = ['primary', 'secondary', 'tertiary', 'quaternary', 'quinary', 'senary', 'septenary']
  const series = (index: number) => {
    const item = chart.series[index]
    const column = index + 1
    const color = excelColor(item.color ?? `var(--color-chart-series-${palette[index % palette.length]})`)
    const line = chart.kind === 'line' || item.reference
    const shape = line
      ? `<c:spPr><a:ln w="${item.reference ? 15875 : 28575}" cap="rnd">${fill(color)}`
        + `${item.reference ? '<a:prstDash val="dash"/>' : ''}<a:round/></a:ln></c:spPr><c:marker><c:symbol val="none"/></c:marker>`
      : chart.kind === 'doughnut' ? ''
        : `<c:spPr>${fill(color)}</c:spPr><c:invertIfNegative val="0"/>`
    const points = (item.pointColors ?? []).map((pointColor, point) => {
      if (!pointColor) return ''
      const pointFill = fill(excelColor(pointColor))
      return chart.kind === 'doughnut'
        ? `<c:dPt><c:idx val="${point}"/><c:bubble3D val="0"/><c:spPr>${pointFill}`
          + `<a:ln w="19050">${fill('FFFFFF')}</a:ln></c:spPr></c:dPt>`
        : `<c:dPt><c:idx val="${point}"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/><c:spPr>${pointFill}</c:spPr></c:dPt>`
    }).join('')
    return `<c:ser><c:idx val="${index}"/><c:order val="${index}"/>`
      + `<c:tx><c:strRef><c:f>${sheet}!${absolute(column, headerRow)}</c:f><c:strCache><c:ptCount val="1"/>`
      + `<c:pt idx="0"><c:v>${escape(item.name)}</c:v></c:pt></c:strCache></c:strRef></c:tx>`
      + shape + points + categories
      + `<c:val><c:numRef><c:f>${sheet}!${absolute(column, first)}:${absolute(column, last)}</c:f>`
      + `<c:numCache><c:formatCode>${escape(formats[index])}</c:formatCode><c:ptCount val="${item.values.length}"/>`
      + item.values.map((value, point) => `<c:pt idx="${point}"><c:v>${value * scales[index]}</c:v></c:pt>`).join('')
      + '</c:numCache></c:numRef></c:val>'
      + (line ? '<c:smooth val="0"/>' : '') + '</c:ser>'
  }
  const main = chart.series.map((item, index) => item.reference ? null : index).filter((index): index is number => index !== null)
  const references = chart.series.map((item, index) => item.reference ? index : null).filter((index): index is number => index !== null)
  const axes = '<c:axId val="1"/><c:axId val="2"/>'
  const lines = (indexes: number[]) => `<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>`
    + `${indexes.map(series).join('')}<c:marker val="1"/>${axes}</c:lineChart>`
  let groups: string
  if (chart.kind === 'doughnut') {
    groups = `<c:doughnutChart><c:varyColors val="1"/>${main.map(series).join('')}`
      + '<c:firstSliceAng val="0"/><c:holeSize val="61"/></c:doughnutChart>'
  } else if (chart.kind === 'line') {
    groups = lines([...main, ...references])
  } else {
    groups = `<c:barChart><c:barDir val="${chart.kind === 'bar' ? 'bar' : 'col'}"/><c:grouping val="clustered"/>`
      + `<c:varyColors val="0"/>${main.map(series).join('')}<c:gapWidth val="${chart.kind === 'bar' ? 60 : 30}"/>${axes}</c:barChart>`
      + (references.length ? lines(references) : '')
  }
  const horizontal = chart.kind === 'bar'
  const minimum = chart.axisMinimum === undefined ? '' : `<c:min val="${chart.axisMinimum * (scales[0] ?? 1)}"/>`
  // A date along the bottom is slanted, 45 degrees up: level, Excel wrapped
  // "Sep 17, 2026" onto three lines.
  const axisText = (slant = false) => `<c:txPr><a:bodyPr${slant ? ' rot="-2700000" vert="horz"' : ''}/><a:lstStyle/>`
    + `<a:p><a:pPr><a:defRPr sz="900">${fill(muted)}</a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>`
  const axisXml = chart.kind === 'doughnut' ? ''
    // A ranking reads top down, as on the page: its categories reversed, and
    // the value axis kept at the bottom by crossing at the last of them.
    : `<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="${horizontal ? 'maxMin' : 'minMax'}"/></c:scaling>`
      + `<c:delete val="0"/><c:axPos val="${horizontal ? 'l' : 'b'}"/><c:numFmt formatCode="General" sourceLinked="0"/>`
      + `<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>`
      + `<c:spPr><a:ln w="6350">${fill(border)}</a:ln></c:spPr>${axisText(!horizontal)}`
      + '<c:crossAx val="2"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/>'
      + '<c:noMultiLvlLbl val="0"/></c:catAx>'
      + `<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/>${minimum}</c:scaling><c:delete val="0"/>`
      + `<c:axPos val="${horizontal ? 'b' : 'l'}"/><c:majorGridlines><c:spPr><a:ln w="6350">${fill(grid)}</a:ln></c:spPr></c:majorGridlines>`
      + `<c:numFmt formatCode="${escape(formats[0] ?? 'General')}" sourceLinked="0"/>`
      + '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
      + `<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>${axisText()}`
      + `<c:crossAx val="1"/><c:crosses val="${horizontal ? 'max' : 'autoZero'}"/><c:crossBetween val="between"/></c:valAx>`
  const legend = chart.kind === 'doughnut' || chart.series.length > 1
    ? `<c:legend><c:legendPos val="${chart.kind === 'doughnut' ? 'r' : 'b'}"/><c:overlay val="0"/></c:legend>` : ''
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="${CHART}" xmlns:a="${DRAWING}" xmlns:r="${RELATIONSHIPS}"><c:roundedCorners val="0"/>`
    + `<c:chart><c:title><c:tx>${richText(chart.title, 1200, true)}</c:tx><c:overlay val="0"/></c:title>`
    + `<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/>${groups}${axisXml}</c:plotArea>${legend}`
    + '<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
    + `<c:spPr>${fill('FFFFFF')}<a:ln w="9525">${fill(border)}</a:ln></c:spPr>`
    + `<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900">${fill(muted)}`
    + '<a:latin typeface="Calibri"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr></c:chartSpace>'
}

/** A sheet's drawing part: each of its charts at its place and size, from the
 * cell its left edge falls in, once the sheet's column widths are final. */
function drawingXml(sheet: Sheet) {
  const EMU = 9525 // per pixel
  const anchor = (x: number) => {
    let column = 0
    while (x >= columnPixels(sheet.widths[column])) {
      x -= columnPixels(sheet.widths[column])
      column += 1
    }
    return { column, offset: x }
  }
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="${SHEET_DRAWING}" xmlns:a="${DRAWING}" xmlns:r="${RELATIONSHIPS}" xmlns:c="${CHART}">`
    + sheet.charts.map((placed, index) => {
      const { column, offset } = anchor(placed.x)
      return `<xdr:oneCellAnchor><xdr:from><xdr:col>${column}</xdr:col><xdr:colOff>${offset * EMU}</xdr:colOff>`
        + `<xdr:row>${placed.row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>`
        + `<xdr:ext cx="${placed.width * EMU}" cy="${placed.height * EMU}"/>`
        + `<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="${index + 2}" name="${escape(placed.chart.title)}"/>`
        + '<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
        + `<a:graphic><a:graphicData uri="${CHART}"><c:chart r:id="rId${index + 1}"/></a:graphicData></a:graphic>`
        + '</xdr:graphicFrame><xdr:clientData/></xdr:oneCellAnchor>'
    }).join('')
    + '</xdr:wsDr>'
}

// --- Writing the workbook ----------------------------------------------------

function escape(text: string) {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
    .replace(/[&<>"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[character] ?? character)
}

function columnName(index: number) {
  let name = ''
  for (let rest = index + 1; rest > 0; rest = Math.floor((rest - 1) / 26)) {
    name = String.fromCharCode(65 + ((rest - 1) % 26)) + name
  }
  return name
}

const reference = (column: number, row: number) => `${columnName(column)}${row + 1}`

// Column widths, in Excel's character units, past which a sheet is wider than a
// laptop's Excel window (about 1,300 px at 7 px a unit) and keeps its first column
// in view while scrolling right.
const PIN_FIRST_COLUMN_WIDTH = 180

function sheetXml(sheet: Sheet) {
  const rows = sheet.rows.map((cells, rowIndex) => {
    const { level, folds } = sheet.outline[rowIndex]
    // Folded rows start hidden under the row that holds them, its + closed.
    const height = sheet.heights?.[rowIndex]
    const attributes = (level ? ' outlineLevel="1" hidden="1"' : folds ? ' collapsed="1"' : '')
      + (height ? ` ht="${height}" customHeight="1"` : '')
    return `<row r="${rowIndex + 1}"${attributes}>${cells.map((cell, column) => {
      const at = reference(column, rowIndex)
      const style = cell.style ? ` s="${cell.style}"` : ''
      if (cell.value === null) return cell.style ? `<c r="${at}"${style}/>` : ''
      if (typeof cell.value === 'number') return `<c r="${at}"${style}><v>${cell.value}</v></c>`
      return `<c r="${at}"${style} t="inlineStr"><is><t xml:space="preserve">${escape(cell.value)}</t></is></c>`
    }).join('')}</row>`
  }).join('')
  const frozen = sheet.frozenRows
  // The first column is pinned only when the columns are wider than a screen:
  // the title lines above the table start in it and run on to the right, and a
  // frozen column's line runs down through them.
  const pinned = sheet.widths.reduce((total, width) => total + (width ?? 0), 0) > PIN_FIRST_COLUMN_WIDTH
  const outlined = sheet.outline.some(row => row.level)
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="${MAIN}" xmlns:r="${RELATIONSHIPS}">`
    // The + on the row that holds the folded rows, above them, not below.
    + (outlined ? '<sheetPr><outlinePr summaryBelow="0"/></sheetPr>' : '')
    + '<sheetViews><sheetView workbookViewId="0">'
    + (!frozen ? '' : pinned
      ? `<pane xSplit="1" ySplit="${frozen}" topLeftCell="${reference(1, frozen)}" activePane="bottomRight" state="frozen"/>`
        + '<selection pane="bottomRight"/>'
      : `<pane ySplit="${frozen}" topLeftCell="${reference(0, frozen)}" activePane="bottomLeft" state="frozen"/>`
        + '<selection pane="bottomLeft"/>')
    + '</sheetView></sheetViews>'
    + `<sheetFormatPr defaultRowHeight="15"${outlined ? ' outlineLevelRow="1"' : ''}/>`
    + `<cols>${sheet.widths.map((width, index) =>
      `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join('')}</cols>`
    + `<sheetData>${rows}</sheetData>`
    + (sheet.merges.length ? `<mergeCells count="${sheet.merges.length}">${sheet.merges.map(range =>
      `<mergeCell ref="${range}"/>`).join('')}</mergeCells>` : '')
    + (sheet.charts.length ? '<drawing r:id="rId1"/>' : '')
    + '</worksheet>'
}

function workbookFiles(sheets: Sheet[], styles: Styles): [string, string][] {
  const header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
  const relationships = (links: [string, string][]) => `${header}<Relationships `
    + 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + links.map(([type, target], index) => `<Relationship Id="rId${index + 1}" Type="${RELATIONSHIPS}/${type}" `
      + `Target="${target}"/>`).join('') + '</Relationships>'
  // A sheet with charts has a drawing, drawingN for the Nth such sheet, which
  // holds them; charts are numbered across the workbook.
  const drawn: [string, string][] = []
  const types: string[] = []
  let drawings = 0, charts = 0
  sheets.forEach((sheet, index) => {
    if (!sheet.charts.length) return
    drawings += 1
    drawn.push([`xl/worksheets/_rels/sheet${index + 1}.xml.rels`,
      relationships([['drawing', `../drawings/drawing${drawings}.xml`]])])
    drawn.push([`xl/drawings/drawing${drawings}.xml`, drawingXml(sheet)])
    types.push(`<Override PartName="/xl/drawings/drawing${drawings}.xml" `
      + 'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
    const links: [string, string][] = []
    for (const placed of sheet.charts) {
      charts += 1
      links.push(['chart', `../charts/chart${charts}.xml`])
      drawn.push([`xl/charts/chart${charts}.xml`, chartXml(placed, placed.dataSheet)])
      types.push(`<Override PartName="/xl/charts/chart${charts}.xml" `
        + 'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
    }
    drawn.push([`xl/drawings/_rels/drawing${drawings}.xml.rels`, relationships(links)])
  })
  return [
    ['[Content_Types].xml', `${header}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" '
      + 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/styles.xml" '
      + 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
      + sheets.map((_, index) => `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" `
        + 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>').join('')
      + types.join('')
      + '</Types>'],
    ['_rels/.rels', `${header}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
      + `<Relationship Id="rId1" Type="${RELATIONSHIPS}/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ['xl/workbook.xml', `${header}<workbook xmlns="${MAIN}" xmlns:r="${RELATIONSHIPS}"><bookViews><workbookView/></bookViews>`
      + `<sheets>${sheets.map((sheet, index) =>
        `<sheet name="${escape(sheet.name)}" sheetId="${index + 1}"${sheet.hidden ? ' state="hidden"' : ''} `
        + `r:id="rId${index + 1}"/>`).join('')}</sheets></workbook>`],
    ['xl/_rels/workbook.xml.rels', `${header}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
      + sheets.map((_, index) => `<Relationship Id="rId${index + 1}" Type="${RELATIONSHIPS}/worksheet" `
        + `Target="worksheets/sheet${index + 1}.xml"/>`).join('')
      + `<Relationship Id="rId${sheets.length + 1}" Type="${RELATIONSHIPS}/styles" Target="styles.xml"/></Relationships>`],
    ['xl/styles.xml', styles.xml()],
    ...sheets.map((sheet, index): [string, string] => [`xl/worksheets/sheet${index + 1}.xml`, sheetXml(sheet)]),
    ...drawn,
  ]
}

// --- Zip, deflated where the browser can, else stored ------------------------

const CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index
  for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
  return value >>> 0
})

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

/** Raw deflate, as a zip holds it, by the browser's own CompressionStream; null
 * where there is none, and the file is stored instead. A sheet with every
 * employee folded in runs to tens of MB of XML stored, a few MB deflated. */
async function deflate(data: Uint8Array) {
  if (typeof CompressionStream === 'undefined') return null
  try {
    const stream = new Blob([data as BlobPart]).stream().pipeThrough(new CompressionStream('deflate-raw'))
    return new Uint8Array(await new Response(stream).arrayBuffer())
  } catch {
    return null
  }
}

async function zip(files: [string, string][]) {
  const encoder = new TextEncoder()
  const now = new Date()
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2)
  const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()
  const parts: Uint8Array[] = []
  const central: Uint8Array[] = []
  let offset = 0
  for (const [name, text] of files) {
    const path = encoder.encode(name)
    const raw = encoder.encode(text)
    const crc = crc32(raw)
    const packed = await deflate(raw)
    const data = packed ?? raw
    const method = packed ? 8 : 0
    const local = new DataView(new ArrayBuffer(30))
    local.setUint32(0, 0x04034b50, true)
    local.setUint16(4, 20, true)
    local.setUint16(6, 0x0800, true) // names in UTF-8
    local.setUint16(8, method, true) // deflated or stored
    local.setUint16(10, time, true)
    local.setUint16(12, date, true)
    local.setUint32(14, crc, true)
    local.setUint32(18, data.length, true)
    local.setUint32(22, raw.length, true)
    local.setUint16(26, path.length, true)
    local.setUint16(28, 0, true)
    const entry = new DataView(new ArrayBuffer(46))
    entry.setUint32(0, 0x02014b50, true)
    entry.setUint16(4, 20, true)
    entry.setUint16(6, 20, true)
    entry.setUint16(8, 0x0800, true)
    entry.setUint16(10, method, true)
    entry.setUint16(12, time, true)
    entry.setUint16(14, date, true)
    entry.setUint32(16, crc, true)
    entry.setUint32(20, data.length, true)
    entry.setUint32(24, raw.length, true)
    entry.setUint16(28, path.length, true)
    entry.setUint32(42, offset, true)
    parts.push(new Uint8Array(local.buffer), path, data)
    central.push(new Uint8Array(entry.buffer), path)
    offset += 30 + path.length + data.length
  }
  const size = central.reduce((total, part) => total + part.length, 0)
  const end = new DataView(new ArrayBuffer(22))
  end.setUint32(0, 0x06054b50, true)
  end.setUint16(8, files.length, true)
  end.setUint16(10, files.length, true)
  end.setUint32(12, size, true)
  end.setUint32(16, offset, true)
  return new Blob([...parts, ...central, new Uint8Array(end.buffer)] as BlobPart[],
    { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
}

/** The report as an .xlsx file: its own sheets when it gives them (`given`,
 * registerExcelSheets), else every table in `content` that has rows, one sheet
 * each. */
/** One view of the report as it stood when read: its tables, and its charts
 * by the table above them on the page, those above every table apart. */
export type PageCapture = { tables: ExcelTable[]; charts: ChartOnPage[][]; leading: ChartOnPage[] }

/** Read the report's tables and charts, in page order, as they are now. */
export function capturePage(content: Element): PageCapture {
  const tables: ExcelTable[] = []
  const charts: ChartOnPage[][] = []
  const leading: ChartOnPage[] = []
  const origin = content.getBoundingClientRect()
  for (const element of content.querySelectorAll('.report-table, [data-excel-chart]')) {
    if (element.matches('[data-excel-chart]')) {
      const chart = excelChartOf(element)
      const rect = element.getBoundingClientRect()
      const box = { left: rect.left - origin.left, top: rect.top - origin.top, width: rect.width, height: rect.height }
      if (chart) (charts.at(-1) ?? leading).push({ chart, box })
    } else {
      const table = domTable(element)
      if (table) {
        tables.push(table)
        charts.push([])
      }
    }
  }
  return { tables, charts, leading }
}

/** A view's sheets in the workbook: the report as shown, or one location of its
 * drilldown, whose `name` names its sheets and heads their titles. `details`
 * are the lines under each sheet's title: range, location, filters. */
export type WorkbookPage = { capture: PageCapture; details: ExcelDetail[]; name?: string }

/** The workbook: each view's tables as sheets, the report as shown first, each
 * chart on the sheet of the table above it on the page (any above every table on
 * the first). A report's own sheets (`given`) stand in for the first view's
 * tables, and take its charts. */
export async function reportWorkbook(heading: string, pages: WorkbookPage[], given: ExcelTable[] = []) {
  const styles = new Styles()
  const taken = new Set<string>()
  const sheets: Sheet[] = []
  // The charts' figures, on a sheet of their own, last and hidden.
  const data: Sheet = { name: sheetName('Chart data', taken), rows: [], widths: [], frozenRows: 0, merges: [],
    outline: [], charts: [], hidden: true }
  pages.forEach((page, index) => {
    let { tables } = page.capture
    let charts = page.capture.charts.map(list => [...list])
    const leading = [...page.capture.leading]
    if (!tables.length && !leading.length && !(index === 0 && given.length)) {
      if (index === 0) throw new Error('There is no table with rows on the page to export.')
      return
    }
    // A report's own sheets, each its own (a role table per location), the
    // page's charts on the first.
    if (index === 0 && given.length) {
      given.forEach((table, tableIndex) => {
        const own = table.name ?? table.title
        sheets.push(sheetFrom([table], [tableIndex ? [] : [...leading, ...charts.flat()]], sheetName(own, taken),
          table.title, heading, page.details, styles, data))
      })
      return
    }
    // Charts and no table: a sheet of the charts alone.
    if (!tables.length) {
      tables = [{ title: 'Charts', columns: [], rows: [] }]
      charts = [[]]
    }
    charts[0].unshift(...leading)
    // One sheet for the view: its tables one under another, as the page has them.
    const first = tables[0]
    const name = page.name ?? first.name ?? first.title
    const title = page.name ? `${page.name} · ${first.title}` : first.title
    sheets.push(sheetFrom(tables, charts, sheetName(name, taken), title, heading, page.details, styles, data))
  })
  if (data.rows.length) sheets.push(data)
  return zip(workbookFiles(sheets, styles))
}
