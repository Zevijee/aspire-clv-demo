import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { BooleanBadge } from '../../../shared/components/BooleanBadge'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getMedicaidWorksheet, getWorksheetCatalog, medicaidWorksheetBase, worksheetDateBasis, worksheetFilterOptions,
  type MedicaidWorksheetRow, type WorksheetCatalog, type WorksheetField, type WorksheetQuery,
} from '../worksheetApi'
import { CellPart, NtaCell, dateLabel, type OpenEditor } from './PdpmWorksheet'
import { WorksheetCellEditor } from './WorksheetCellEditor'

const pageSize = 50

/** Medicaid PDPM Worksheet: the Medicare PDPM Worksheet for Texas Medicaid
 * stays, with the cells Texas's case mix needs -- nursing, NTA and a projected
 * two-letter code -- in the same shared, append-only log. */
export function MedicaidWorksheet() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const dateBasis = worksheetDateBasis(params)
  const [catalog, setCatalog] = useState<WorksheetCatalog | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [query, setQuery] = useState<WorksheetQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, dateBasis, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  // Bumped after a save: reloads the rows without a loading flash.
  const [refresh, setRefresh] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: MedicaidWorksheetRow[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  const [editing, setEditing] = useState<{ row: MedicaidWorksheetRow; field: WorksheetField } | null>(null)
  const onQueryChange = useCallback((next: WorksheetQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getWorksheetCatalog(controller.signal, medicaidWorksheetBase)
      .then(data => { if (!controller.signal.aborted) setCatalog(data) })
      .catch((error: Error) => { if (!controller.signal.aborted) setCatalogError(error.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getMedicaidWorksheet(startDate, endDate, dateBasis, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, dateBasis, pageIndex, query, requestKey, refresh])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : catalogError
  const status = { loading: (result === null || catalog === null) && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const editingRow = editing && (result?.items.find(row => row.payer_stay_id === editing.row.payer_stay_id) ?? editing.row)

  const groups = new Map<string, WorksheetField[]>()
  for (const field of catalog?.fields ?? []) groups.set(field.group, [...(groups.get(field.group) ?? []), field])
  const open = (row: MedicaidWorksheetRow): OpenEditor => field => setEditing({ row, field })
  const componentColumns: TableColumn<MedicaidWorksheetRow>[] = [...groups].map(([group, fields]) => ({
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
  const columns: TableColumn<MedicaidWorksheetRow>[] = [
    { id: 'resident', header: 'Name', isRowHeader: true, truncate: false, value: row => row.resident_name,
      format: (_, row) => <span className="worksheet-name">
        <span>{row.resident_name}</span>
        <span className="worksheet-name__facility">
          <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>{row.facility_name}</LocationName>
        </span>
      </span> },
    { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
      format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
        {row.facility_name}</LocationName> },
    { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
    { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
    { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
    { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
    // With how the Medicaid stay began: at admission, or by a payer change.
    { id: 'medicaid-start', header: 'Stay start', value: row => row.medicaid_start, truncate: false,
      exportValue: row => `${row.medicaid_start} (${row.start_reason})`,
      format: (_, row) => <span className="worksheet-stack">
        <span>{dateLabel(row.medicaid_start)}</span>
        <span className="worksheet-stack__detail">{row.start_reason}</span>
      </span> },
    { id: 'ard', header: 'ARD', value: row => row.ard ?? '', format: (_, row) => dateLabel(row.ard) },
    { id: 'mds-due', header: 'MDS due', filterable: true, value: row => row.mds_status,
      exportValue: row => row.due_date ?? 'Complete',
      format: (_, row) => row.mds_status === 'Complete'
        ? <span className="boolean-badge boolean-badge--yes">Complete</span>
        : <span className={row.mds_status === 'Overdue' ? 'worksheet-due worksheet-due--overdue' : 'worksheet-due'}>
          {dateLabel(row.due_date)}{row.mds_status === 'Overdue' ? ' · Overdue' : ''}</span> },
    // The components, then the projected code worked out from them, then the
    // final code the coded assessment gave.
    ...componentColumns.filter(column => column.id !== 'cell-Projected code'),
    ...componentColumns.filter(column => column.id === 'cell-Projected code'),
    { id: 'final-code', header: 'Final code', sortable: false, truncate: false, value: row => row.final_code ?? '',
      format: (_, row) => row.final_code
        ? <span className="care-code worksheet-cell__value">{row.final_code}</span>
        : <span className="worksheet-cell__value--empty">Not coded yet</span> },
    { id: 'active', header: 'Active', filterable: true, truncate: false, value: row => row.active,
      exportValue: row => row.end_reason ? `No (${row.end_reason}, ${row.ended_on})` : row.active,
      format: (_, row) => <span className="worksheet-stack">
        <span><BooleanBadge value={row.active === 'Yes'} /></span>
        {row.end_reason && <>
          <span className="worksheet-stack__detail">{row.end_reason}</span>
          <span className="worksheet-stack__detail">{dateLabel(row.ended_on)}</span>
        </>}
      </span> },
  ]
  // Only the columns people edit -- the component cells -- can be resized.
  const tableColumns = columns.map(column => column.id.startsWith('cell-') ? column : { ...column, resizable: false })

  return <div className="pdpm-worksheet">
    <Table<MedicaidWorksheetRow> {...status}
      title="Medicaid PDPM worksheet"
      subtitle={'Every Texas Medicaid stay -- Texas Medicaid pays on the PDPM nursing and NTA components; Florida '
        + `and Pennsylvania use other systems -- whose ${dateBasis === 'ard' ? 'first assessment ARD' : 'stay start'} `
        + `falls from ${startDate} to ${endDate}, including stays that have since ended. Stay start is the first `
        + `day on this Medicaid payer. Active is whether this Medicaid stay is still running${censusDate
          ? ` on ${censusDate}` : ''}. MDS due is ${catalog?.mds_due_days ?? 14} days after the ARD, or Complete `
        + 'once coded. The code is two letters, nursing then NTA; the final code fills in from the first '
        + 'assessment once it is coded. A number beside a title shows how many entries it has.'}
      columns={tableColumns} rows={result?.items ?? []} getRowKey={row => row.payer_stay_id}
      initialSort={{ columnId: 'resident', direction: 'ascending' }}
      internalScroll alignTop resizableColumns stickyFirstColumn searchable serverSide clearableFilters
      filterSource={{ id: 'medicaid-pdpm-worksheet', startDate, endDate,
        endpoint: worksheetFilterOptions(dateBasis, medicaidWorksheetBase) }}
      onQueryChange={onQueryChange} totalRows={result?.total}
      emptyMessage="No residents match these filters."
      csvFileName={`medicaid-pdpm-worksheet-${censusDate || 'today'}.csv`}
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
    {editing && editingRow && <WorksheetCellEditor row={editingRow} field={editing.field} base={medicaidWorksheetBase}
      onClose={() => setEditing(null)} onSaved={() => setRefresh(count => count + 1)} />}
  </div>
}
