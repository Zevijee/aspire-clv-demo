import { Tooltip } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getWorksheet, getWorksheetCatalog, worksheetFilterOptions,
  type WorksheetCatalog, type WorksheetField, type WorksheetQuery, type WorksheetRow,
} from '../worksheetApi'
import { WorksheetCellEditor } from './WorksheetCellEditor'

const pageSize = 50
const dateLabel = (value: string | null) => value
  ? new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'

const entered = (value: string) => new Date(value).toLocaleString(undefined,
  { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
const entriesLabel = (count: number) => `${count} entr${count === 1 ? 'y' : 'ies'}`

/** One part of a component cell, "Name: value", a button that opens its
 * editor. Hovering shows what was entered: the value, its note, who and when. */
// Opens a part's editor. Only a part's title does; its value and note are text.
type OpenEditor = (field: WorksheetField) => void

function CellPart({ field, row, onOpen }: {
  field: WorksheetField; row: WorksheetRow; onOpen: OpenEditor
}) {
  const cell = row.cells[field.id]
  const activity = row.activity[field.id] ?? 0
  const single = field.group === field.label
  const name = single ? field.label : `${field.group} ${field.label}`
  // A Reply is text only: its note is what it says.
  const text = field.kind === 'text'
  const shown = text ? cell?.note : cell?.label
  const details = <div className="worksheet-tooltip">
    <p className="worksheet-tooltip__title">{name}</p>
    {cell ? <>
      {!text && <p><strong className={field.kind === 'hipps' ? 'care-code' : undefined}>{cell.label}</strong></p>}
      {cell.note && <p className="worksheet-tooltip__note">{cell.note}</p>}
      <p className="worksheet-tooltip__meta">{cell.author}, {entered(cell.created_at)} · {entriesLabel(activity)}</p>
    </> : <p className="worksheet-tooltip__meta">Nothing entered yet.</p>}
    <p className="worksheet-tooltip__meta">Click to {cell ? 'edit' : 'add'}.</p>
  </div>
  // Only the title is a link, styled as the drilldown links are; the value and
  // note beside it are plain text.
  return <div className="worksheet-cell__part">
    <Tooltip title={details} placement="right" mouseEnterDelay={0.3}>
      <button type="button" className="drilldown-table__link worksheet-cell__title" onClick={() => onOpen(field)}
        aria-label={`${name}: ${shown ?? 'not entered'}. Edit`}>{field.label}:</button>
    </Tooltip>
    {shown ? <span className={text ? 'worksheet-cell__reply'
      : `worksheet-cell__value${field.kind === 'hipps' ? ' care-code' : ''}`}>{shown}</span>
      : <span className="worksheet-cell__empty-tag">Empty</span>}
    {activity > 1 && <span className="worksheet-cell__activity" aria-label={entriesLabel(activity)}>{activity}</span>}
    {!text && cell?.note && <span className="worksheet-cell__note">{cell.note}</span>}
  </div>
}

/** The NTA cell, "Diagnoses: points and band" then each diagnosis; hovering
 * lists them with their points and notes. */
function NtaCell({ field, row, onOpen }: {
  field: WorksheetField; row: WorksheetRow; onOpen: OpenEditor
}) {
  const activity = row.activity[field.id] ?? 0
  const details = <div className="worksheet-tooltip">
    <p className="worksheet-tooltip__title">NTA · {row.nta.points} points · NTA {row.nta.band}</p>
    {row.nta.items.length ? row.nta.items.map(item => <p key={item.value}>
      <strong>{item.label}</strong> · {item.points} pt{item.points === 1 ? '' : 's'}
      {item.note && <span className="worksheet-tooltip__note"> — {item.note}</span>}
    </p>) : <p className="worksheet-tooltip__meta">No diagnoses yet.</p>}
    <p className="worksheet-tooltip__meta">{activity ? `${entriesLabel(activity)} · ` : ''}Click to {
      row.nta.items.length ? 'edit' : 'add'}.</p>
  </div>
  return <div className="worksheet-cell__part worksheet-cell__part--list">
    <span className="worksheet-cell__line">
      <Tooltip title={details} placement="right" mouseEnterDelay={0.3}>
        <button type="button" className="drilldown-table__link worksheet-cell__title" onClick={() => onOpen(field)}
          aria-label={`NTA: ${row.nta.items.length} diagnoses, ${row.nta.points} points. Edit`}>{field.label}:</button>
      </Tooltip>
      {row.nta.items.length ? <span className="worksheet-cell__value">{row.nta.points} pts · NTA {row.nta.band}</span>
        : <span className="worksheet-cell__empty-tag">Empty</span>}
      {activity > 0 && <span className="worksheet-cell__activity" aria-label={entriesLabel(activity)}>{activity}</span>}
    </span>
    {row.nta.items.map(item => <span key={item.value} className="worksheet-cell__item">
      {item.label}
      {item.note && <span className="worksheet-cell__note">{item.note}</span>}
    </span>)}
  </div>
}

/** PDPM Worksheet: today's PDPM residents, with their ARD and MDS due date, and
 * the PT/OT, SLP, nursing and NTA components and HIPPS codes people enter.
 * Every entry is saved to the API's log, so everyone sees and answers it. */
export function PdpmWorksheet() {
  // The header's date range: which Medicare stay starts the worksheet lists.
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [catalog, setCatalog] = useState<WorksheetCatalog | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [query, setQuery] = useState<WorksheetQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  // Bumped after a save: reloads the rows without changing the request key, so
  // the table keeps showing them rather than flashing a loading state.
  const [refresh, setRefresh] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: WorksheetRow[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  // The cell being edited. The row is kept so the editor stays open while the
  // page reloads after a save, then follows the reloaded row.
  const [editing, setEditing] = useState<{ row: WorksheetRow; field: WorksheetField } | null>(null)
  const onQueryChange = useCallback((next: WorksheetQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getWorksheetCatalog(controller.signal)
      .then(data => { if (!controller.signal.aborted) setCatalog(data) })
      .catch((error: Error) => { if (!controller.signal.aborted) setCatalogError(error.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getWorksheet(startDate, endDate, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, pageIndex, query, requestKey, refresh])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : catalogError
  const status = { loading: (result === null || catalog === null) && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const editingRow = editing && (result?.items.find(row => row.payer_stay_id === editing.row.payer_stay_id) ?? editing.row)

  const groups = new Map<string, WorksheetField[]>()
  for (const field of catalog?.fields ?? []) groups.set(field.group, [...(groups.get(field.group) ?? []), field])
  const open = (row: WorksheetRow): OpenEditor => field => setEditing({ row, field })
  const componentColumns: TableColumn<WorksheetRow>[] = [...groups].map(([group, fields]) => ({
    id: `cell-${group}`, header: group, sortable: false, truncate: false,
    value: row => fields.map(field => row.cells[field.id]?.label ?? '').join(' / '),
    exportValue: row => group === 'NTA' ? row.nta.items.map(item => item.label).join('; ')
      : fields.map(field => `${field.group === field.label ? '' : `${field.label}: `}${row.cells[field.id]?.label ?? ''}`).join('; '),
    format: (_, row) => <div className="worksheet-cell">
      {fields.map(field => field.kind === 'diagnoses'
        ? <NtaCell key={field.id} field={field} row={row} onOpen={open(row)} />
        : <CellPart key={field.id} field={field} row={row} onOpen={open(row)} />)}
    </div>,
  }))

  // Column ids match the API's sort and filter allowlists.
  const columns: TableColumn<WorksheetRow>[] = [
    { id: 'resident', header: 'Name', isRowHeader: true, value: row => row.resident_name },
    { id: 'payer', header: 'Payer', filterable: true, value: row => row.payer_label },
    { id: 'medicare-start', header: 'Stay start', value: row => row.medicare_start,
      format: (_, row) => dateLabel(row.medicare_start) },
    { id: 'active', header: 'Active', filterable: true, dataType: 'boolean', value: row => row.active },
    { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
      format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
        {row.facility_name}</LocationName> },
    { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
    { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
    { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
    { id: 'ard', header: 'ARD', value: row => row.ard ?? '', format: (_, row) => dateLabel(row.ard) },
    { id: 'mds-due', header: 'MDS due', filterable: true, value: row => row.mds_status,
      exportValue: row => row.due_date ?? 'Complete',
      format: (_, row) => row.mds_status === 'Complete'
        ? <span className="boolean-badge boolean-badge--yes">Complete</span>
        : <span className={row.mds_status === 'Overdue' ? 'worksheet-due worksheet-due--overdue' : 'worksheet-due'}>
          {dateLabel(row.due_date)}{row.mds_status === 'Overdue' ? ' · Overdue' : ''}</span> },
    // Projected and final HIPPS first, side by side, then the components.
    ...componentColumns.filter(column => column.id === 'cell-Projected HIPPS'),
    // Not entered: filled from the coded assessment, so it can be checked
    // against the projected HIPPS beside it.
    { id: 'final-hipps', header: 'Final HIPPS', sortable: false, value: row => row.final_hipps ?? '',
      format: (_, row) => row.final_hipps ? <span className="care-code">{row.final_hipps}</span>
        : <span className="worksheet-cell__value--empty">Not coded yet</span> },
    ...componentColumns.filter(column => column.id !== 'cell-Projected HIPPS'),
  ]

  return <>
    <Table<WorksheetRow> {...status}
      title="PDPM worksheet"
      subtitle={`Every Federal Medicare and Managed Medicare PDPM stay that started from ${startDate} to ${endDate}, `
        + 'including stays that have since ended. Stay start is the first day on this Medicare payer. '
        + `Active is whether this Medicare stay is still running${censusDate ? ` on ${censusDate}` : ''}; `
        + 'a resident can stay in the building on another payer after it ends. '
        + `MDS due is ${catalog?.mds_due_days ?? 14} days after the ARD, or Complete once coded. `
        + 'Final HIPPS fills in from the assessment once it is coded: its PDPM code and 1, the 5-day indicator. '
        + 'Click any part of PT/OT, SLP, Nursing, NTA or Projected HIPPS to enter it, add a note, '
        + 'and read or reply to what others have entered. A number shows how many entries a part has.'}
      columns={columns} rows={result?.items ?? []} getRowKey={row => row.payer_stay_id}
      initialSort={{ columnId: 'resident', direction: 'ascending' }}
      internalScroll alignTop resizableColumns stickyFirstColumn searchable serverSide clearableFilters
      filterSource={{ id: 'pdpm-worksheet', startDate, endDate,
        endpoint: worksheetFilterOptions }}
      onQueryChange={onQueryChange} totalRows={result?.total}
      emptyMessage="No residents match these filters."
      csvFileName={`pdpm-worksheet-${censusDate || 'today'}.csv`}
      footer={<nav aria-label="Worksheet pagination" className="report-table__pagination">
        <span className="report-table__pagination-summary" role="status" aria-live="polite">
          {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} residents`
            : error ? 'Pagination unavailable' : 'Loading residents…'}
        </span>
        <div className="report-table__pagination-actions">
          {[
            { label: 'First page', symbol: '«', index: 0, disabled: pageIndex === 0 },
            { label: 'Previous page', symbol: '‹', index: pageIndex - 1, disabled: pageIndex === 0 },
            { label: 'Next page', symbol: '›', index: pageIndex + 1, disabled: pageIndex + 1 >= pageCount },
            { label: 'Last page', symbol: '»', index: pageCount - 1, disabled: pageIndex + 1 >= pageCount },
          ].map(({ label, symbol, index, disabled }) => <button key={label} type="button"
            className="report-table__pagination-arrow" aria-label={label} title={label}
            disabled={status.loading || !!error || disabled} onClick={() => setPage({ queryKey, index })}>
            <span aria-hidden="true">{symbol}</span>
          </button>)}
        </div>
      </nav>}
    />
    {editing && editingRow && <WorksheetCellEditor row={editingRow} field={editing.field}
      onClose={() => setEditing(null)} onSaved={() => setRefresh(count => count + 1)} />}
  </>
}
