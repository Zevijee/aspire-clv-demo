import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  downloadMovementLogs, getMovementLogs, netChangeBase,
  type Movement, type MovementLogsQuery,
} from '../api/netChangeOverview'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})

// Column ids match the API's allowlist exactly: sorting and filtering happen on
// the server, so an id that does not match is silently unsortable.
const columns: TableColumn<Movement>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'move-type', header: 'Move type', filterable: true, value: row => row.move_type },
  { id: 'move-date', header: 'Date', initialSortDirection: 'descending', value: row => row.move_date,
    format: (_, row) => dateFormat.format(new Date(`${row.move_date}T00:00:00Z`)) },
  { id: 'description', header: 'Description', value: row => row.description },
  { id: 'los_days', header: 'LOS (days)', numeric: true, value: row => row.los_days ?? '—' },
]

export function NetChangeLogs() {
  const [params] = useSearchParams()
  // A drill-down scope arrives as location names; carry it into the logs as the
  // same filters the table itself uses.
  const initialFilters: Record<string, string[]> = {}
  const keys = ['state', 'portfolio', 'region', 'facility']
  params.getAll('net_scope').slice(0, 4).forEach((value, index) => {
    initialFilters[keys[index]] = [value]
  })
  return <NetChangeLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function NetChangeLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<MovementLogsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: Movement[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: MovementLogsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getMovementLogs(startDate, endDate, pageIndex * pageSize, query, controller.signal)
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
  return <Table<Movement> {...status}
    title="Movement logs"
    subtitle="Every admission, discharge and payer change in the selected date range."
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.move_id}
    initialSort={{ columnId: 'move-date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    onClearFilters={() => {
      const next = new URLSearchParams(params)
      let changed = false
      for (const key of [...next.keys()]) if (key.startsWith('logs_')) { next.delete(key); changed = true }
      if (changed) setParams(next)
    }}
    filterSource={{ id: 'net-change-logs', startDate, endDate, endpoint: `${netChangeBase}/logs/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No movements match the selected dates and filters."
    csvFileName={`net-change-logs-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadMovementLogs(startDate, endDate, query)}
    footer={<nav aria-label="Movement log pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} movements`
          : error ? 'Pagination unavailable' : 'Loading movements…'}
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
