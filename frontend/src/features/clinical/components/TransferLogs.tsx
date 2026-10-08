import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { payerLabel, payerLabels } from '../../adt/api/admissionsOverview'
import {
  downloadTransferLogs, getTransferLogs, transferLogsBase, type TransferLog, type TransferLogsQuery,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
// The Overview's drilldown, one level per location filter, in path order.
const locationFilters = ['state', 'portfolio', 'region', 'facility']

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<TransferLog>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'admission-date', header: 'Admission date', value: row => row.admission_date,
    format: (_, row) => day(row.admission_date) },
  { id: 'transfer-date', header: 'Transfer date', initialSortDirection: 'descending',
    value: row => row.transfer_date, format: (_, row) => day(row.transfer_date) },
  { id: 'length-of-stay', header: 'Length of stay (days)', numeric: true, value: row => row.length_of_stay },
  { id: 'hospital', header: 'Transferred to', filterable: true, value: row => row.hospital_name },
  { id: 'reason', header: 'Reason', filterable: true, value: row => row.reason },
  // Yes is the outcome to bring down, so it reads red.
  { id: 'within-30-days', header: 'Within 30 days', filterable: true, dataType: 'boolean', negativeWhenTrue: true,
    value: row => row.within_30_days },
  { id: 'admission-source', header: 'Admitted from', filterable: true, value: row => row.admission_source },
  { id: 'rehospitalization', header: 'Rehospitalization', filterable: true, dataType: 'boolean', negativeWhenTrue: true,
    value: row => row.rehospitalization },
  { id: 'payer', header: 'Payer type', filterable: true, value: row => payerLabel(row.payer_type) },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
]

/** The Logs tab: every hospital transfer in the date range, paged, sorted and
 * filtered by the API. It opens on the Overview's selection -- its drilldown
 * location and its payer and reason filters -- so it lists the transfers the
 * Overview counted. */
export function TransferLogs() {
  const [params] = useReportSearchParams()
  const initialFilters: Record<string, string[]> = {}
  params.getAll('drill').forEach((name, index) => { initialFilters[locationFilters[index]] = [name] })
  const payers = params.getAll('transfer_payer').map(payer => payerLabels[payer] ?? payer)
  if (payers.length) initialFilters.payer = payers
  const reasons = params.getAll('transfer_reason')
  if (reasons.length) initialFilters.reason = reasons
  return <TransferLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function TransferLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<TransferLogsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: TransferLog[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: TransferLogsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getTransferLogs(startDate, endDate, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResponse({ key: requestKey, items: data.items, total: data.total })
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <Table<TransferLog> {...status}
    title="Hospital transfer logs"
    subtitle={'Every transfer to a hospital in the date range. Length of stay is the days from admission to the '
      + 'transfer. Within 30 days means no more than 30 days after '
      + 'admission; a rehospitalization was admitted from a hospital and sent back within 30 days.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.transfer_id}
    initialSort={{ columnId: 'transfer-date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    filterSource={{ id: 'hospital-transfers', startDate, endDate, endpoint: `${transferLogsBase}/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No transfers match the selected dates and filters."
    csvFileName={`hospital-transfers-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadTransferLogs(startDate, endDate, query)}
    footer={<nav aria-label="Transfer log pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} transfers`
          : error ? 'Pagination unavailable' : 'Loading transfers…'}
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
}
