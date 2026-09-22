import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { payerLabel } from '../api/admissionsOverview'
import {
  dischargesBase, downloadDischargeLogs, getDischargeLogs,
  type Discharge, type DischargeLogsQuery,
} from '../api/dischargesOverview'
import { getDischargeLogsFilters } from '../utils/dischargeLogsFilters'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<Discharge>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name },
  { id: 'state', header: 'State', filterable: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, value: row => row.region },
  { id: 'admission-date', header: 'Admission date', value: row => row.admission_date,
    format: (_, row) => day(row.admission_date) },
  { id: 'discharge-date', header: 'Discharge date', initialSortDirection: 'descending',
    value: row => row.discharge_date, format: (_, row) => day(row.discharge_date) },
  { id: 'payer', header: 'Payer type', filterable: true, value: row => payerLabel(row.payer_type) },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'disposition', header: 'Discharge type', filterable: true, value: row => row.discharge_type },
  { id: 'destination-type', header: 'Destination type', filterable: true, value: row => row.destination_type },
  { id: 'destination', header: 'Destination name', filterable: true, value: row => row.destination_name },
  { id: 'length-of-stay', header: 'LOS (days)', numeric: true, value: row => row.length_of_stay },
]

export function DischargesLogs() {
  const [searchParams] = useSearchParams()
  const initialFilters = getDischargeLogsFilters(searchParams)
  return <DischargesLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function DischargesLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<DischargeLogsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: Discharge[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: DischargeLogsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getDischargeLogs(startDate, endDate, pageIndex * pageSize, query, controller.signal)
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
  return <Table<Discharge> {...status}
    title="Discharge Logs" subtitle="Individual discharges in the selected discharge date range"
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.discharge_id}
    initialSort={{ columnId: 'discharge-date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    onClearFilters={() => {
      const next = new URLSearchParams(params)
      let changed = false
      for (const key of [...next.keys()]) if (key.startsWith('logs_')) { next.delete(key); changed = true }
      if (changed) setParams(next)
    }}
    filterSource={{ id: 'discharges', startDate, endDate, endpoint: `${dischargesBase}/logs/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No discharges match the selected dates and filters."
    csvFileName={`discharge-logs-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadDischargeLogs(startDate, endDate, query)}
    footer={<nav aria-label="Discharge log pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} discharges`
          : error ? 'Pagination unavailable' : 'Loading discharges…'}
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
