import { isValidElement, type ReactNode } from 'react'
import { type TableColumn, type TableSections } from './components/Table'
import { tableChange } from './utils/tableChange'

/** The report as it is on screen, as an Excel workbook: one sheet per table, its
 * title and the report's range above it, the header row frozen, figures as
 * numbers in their own format ($, %, decimals, sign) so they sum and sort in
 * Excel, a figure's share after it in the same cell. Read from the page's
 * tables, so it holds what they show -- a paged table, the page shown -- unless
 * the report gives its own sheets (registerExcelSheets, tableToExcel), with rows
 * that fold open under a row, as a role's employees under it. Written as a real
 * .xlsx (zipped XML) with no library. */

type Cell = { value: string | number | null; style: number }
type Sheet = {
  name: string; rows: Cell[][]; widths: number[]; frozenRows: number; merges: string[]
  /** Each row's outline: folded under the row above it (1), or holding such rows. */
  outline: { level: 0 | 1; folds: boolean }[]
}

const MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const RELATIONSHIPS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

// --- Styles -----------------------------------------------------------------

type Font = 0 | 1 | 2 | 3 // regular, bold, title, muted
type Fill = 0 | 2 // none, the header's
type Style = { format: string; font: Font; fill: Fill; indent: number }

// Excel takes some 200 to 250 custom number formats in a workbook, and past that
// repairs the file by discarding the rest: 379 did. A figure's share in its cell
// is a format of its own, so they stop short of it, and any past it are text.
const FORMAT_LIMIT = 180

/** Each distinct look a cell takes, numbered as styles.xml lists them; the
 * first is Excel's default. */
class Styles {
  private readonly styles: Style[] = [{ format: 'General', font: 0, fill: 0, indent: 0 }]
  private readonly keys = new Map<string, number>([['General|0|0|0', 0]])
  private readonly formats = new Set<string>()

  /** Whether a cell can take this number format: one already used, or room for
   * another under Excel's limit (FORMAT_LIMIT). */
  fits(format: string) {
    return this.formats.has(format) || this.formats.size < FORMAT_LIMIT
  }

  get(format = 'General', font: Font = 0, fill: Fill = 0, indent = 0) {
    const key = `${format}|${font}|${fill}|${indent}`
    let index = this.keys.get(key)
    if (index === undefined) {
      index = this.styles.push({ format, font, fill, indent }) - 1
      this.keys.set(key, index)
      if (format !== 'General') this.formats.add(format)
    }
    return index
  }

  xml() {
    const formats = [...new Set(this.styles.map(style => style.format).filter(format => format !== 'General'))]
    const formatId = (format: string) => format === 'General' ? 0 : 164 + formats.indexOf(format)
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="${MAIN}">`
      + `<numFmts count="${formats.length}">${formats.map((format, index) =>
        `<numFmt numFmtId="${164 + index}" formatCode="${escape(format)}"/>`).join('')}</numFmts>`
      + '<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font>'
      + '<font><b/><sz val="11"/><name val="Calibri"/></font>'
      + '<font><b/><sz val="14"/><name val="Calibri"/></font>'
      + '<font><sz val="10"/><color rgb="FF64748B"/><name val="Calibri"/></font></fonts>'
      + '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
      + '<fill><patternFill patternType="solid"><fgColor rgb="FFEEF2F7"/><bgColor indexed="64"/></patternFill></fill></fills>'
      + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
      + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
      + `<cellXfs count="${this.styles.length}">${this.styles.map(style =>
        `<xf numFmtId="${formatId(style.format)}" fontId="${style.font}" fillId="${style.fill}" borderId="0" xfId="0"`
        + ' applyNumberFormat="1" applyFont="1" applyFill="1"'
        + (style.indent ? ` applyAlignment="1"><alignment indent="${style.indent}"/></xf>` : '/>')).join('')}</cellXfs>`
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

/** A table as a sheet: its title, the report's heading and range, the group and
 * header rows, frozen, then its rows, figures as numbers in the page's format,
 * each row's details folded under it. */
function sheetFrom(table: ExcelTable, name: string, heading: string, details: string[], styles: Styles): Sheet {
  const rows: Cell[][] = []
  const outline: Sheet['outline'] = []
  const add = (cells: Cell[], level: 0 | 1 = 0, folds = false) => {
    rows.push(cells)
    outline.push({ level, folds })
  }
  add([{ value: table.title, style: styles.get('General', 2) }])
  add([{ value: heading, style: styles.get('General', 1) }])
  details.forEach(detail => add([{ value: detail, style: styles.get('General', 3) }]))
  add([])

  const header = styles.get('General', 1, 2)
  const merges: string[] = []
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
  const frozenRows = rows.length

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

  const widths: number[] = []
  rows.slice(frozenRows - 1).forEach(row => row.forEach((cell, index) => {
    const shown = typeof cell.value === 'number' ? cell.value.toLocaleString(undefined, { maximumFractionDigits: 2 }).length + 8
      : String(cell.value ?? '').length + 4
    widths[index] = Math.max(widths[index] ?? 8, Math.min(60, shown + 2))
  }))
  return { name, rows, widths, frozenRows, merges, outline }
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

function sheetXml(sheet: Sheet) {
  const rows = sheet.rows.map((cells, rowIndex) => {
    const { level, folds } = sheet.outline[rowIndex]
    // Folded rows start hidden under the row that holds them, its + closed.
    const attributes = level ? ' outlineLevel="1" hidden="1"' : folds ? ' collapsed="1"' : ''
    return `<row r="${rowIndex + 1}"${attributes}>${cells.map((cell, column) => {
      const at = reference(column, rowIndex)
      const style = cell.style ? ` s="${cell.style}"` : ''
      if (cell.value === null) return cell.style ? `<c r="${at}"${style}/>` : ''
      if (typeof cell.value === 'number') return `<c r="${at}"${style}><v>${cell.value}</v></c>`
      return `<c r="${at}"${style} t="inlineStr"><is><t xml:space="preserve">${escape(cell.value)}</t></is></c>`
    }).join('')}</row>`
  }).join('')
  const frozen = sheet.frozenRows
  const outlined = sheet.outline.some(row => row.level)
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="${MAIN}" xmlns:r="${RELATIONSHIPS}">`
    // The + on the row that holds the folded rows, above them, not below.
    + (outlined ? '<sheetPr><outlinePr summaryBelow="0"/></sheetPr>' : '')
    + '<sheetViews><sheetView workbookViewId="0">'
    + `<pane xSplit="1" ySplit="${frozen}" topLeftCell="${reference(1, frozen)}" activePane="bottomRight" state="frozen"/>`
    + '<selection pane="bottomRight"/></sheetView></sheetViews>'
    + `<sheetFormatPr defaultRowHeight="15"${outlined ? ' outlineLevelRow="1"' : ''}/>`
    + `<cols>${sheet.widths.map((width, index) =>
      `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`).join('')}</cols>`
    + `<sheetData>${rows}</sheetData>`
    + (sheet.merges.length ? `<mergeCells count="${sheet.merges.length}">${sheet.merges.map(range =>
      `<mergeCell ref="${range}"/>`).join('')}</mergeCells>` : '')
    + '</worksheet>'
}

function workbookFiles(sheets: Sheet[], styles: Styles): [string, string][] {
  const header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
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
      + '</Types>'],
    ['_rels/.rels', `${header}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
      + `<Relationship Id="rId1" Type="${RELATIONSHIPS}/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ['xl/workbook.xml', `${header}<workbook xmlns="${MAIN}" xmlns:r="${RELATIONSHIPS}"><bookViews><workbookView/></bookViews>`
      + `<sheets>${sheets.map((sheet, index) =>
        `<sheet name="${escape(sheet.name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`).join('')}</sheets></workbook>`],
    ['xl/_rels/workbook.xml.rels', `${header}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
      + sheets.map((_, index) => `<Relationship Id="rId${index + 1}" Type="${RELATIONSHIPS}/worksheet" `
        + `Target="worksheets/sheet${index + 1}.xml"/>`).join('')
      + `<Relationship Id="rId${sheets.length + 1}" Type="${RELATIONSHIPS}/styles" Target="styles.xml"/></Relationships>`],
    ['xl/styles.xml', styles.xml()],
    ...sheets.map((sheet, index): [string, string] => [`xl/worksheets/sheet${index + 1}.xml`, sheetXml(sheet)]),
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
export async function reportWorkbook(content: Element, heading: string, details: string[], given: ExcelTable[] = []) {
  const styles = new Styles()
  const taken = new Set<string>()
  const tables = given.length ? given : [...content.querySelectorAll('.report-table')].map(domTable)
    .filter((table): table is ExcelTable => table !== null)
  if (!tables.length) throw new Error('There is no table with rows on the page to export.')
  const sheets = tables.map(table => sheetFrom(table, sheetName(table.name ?? table.title, taken), heading, details, styles))
  return zip(workbookFiles(sheets, styles))
}
