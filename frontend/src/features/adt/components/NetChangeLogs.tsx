import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn, type TableQuery } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getMovements, type Movement, type MovementsPage } from '../api/movementLogs'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const columns: TableColumn<Movement>[] = [
  { id: 'resident_name', header: 'Resident', isRowHeader: true, filterable: true, value: (row) => row.resident_name },
  { id: 'state', header: 'State', filterable: true, value: (row) => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, value: (row) => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, value: (row) => row.region },
  { id: 'facility_name', header: 'Facility', filterable: true, value: (row) => row.facility_name },
  { id: 'move_type', header: 'Move type', filterable: true, value: (row) => row.move_type },
  { id: 'move_date', header: 'Date', value: (row) => row.move_date,
    format: (_, row) => dateFormat.format(new Date(`${row.move_date}T00:00:00Z`)) },
  { id: 'description', header: 'Description', value: (row) => row.description },
  { id: 'los_days', header: 'LOS (days)', numeric: true, value: (row) => row.los_days ?? '—' },
]

export function NetChangeLogs() {
  const [params] = useSearchParams()
  const initialFilters: Record<string, string[]> = {}
  const keys = ['state', 'portfolio', 'region', 'facility_name']
  params.getAll('net_scope').slice(0, 4).forEach((value, index) => { initialFilters[keys[index]] = [value] })
  return <NetChangeLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function NetChangeLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<TableQuery>({ filters: initialFilters, sort: { columnId: 'move_date', direction: 'descending' }, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; data: MovementsPage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: TableQuery) => {
    setQuery((current) => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getMovements(startDate, endDate, pageIndex * pageSize, query, false, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const loading = result === null && error === null
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <Table<Movement>
    title="Movement Logs" subtitle="Admissions, discharges, and payer changes in the selected dates. LOS is the completed stay for a discharge or the previous payer period for a payer change; admissions show —."
    columns={columns} rows={result?.items ?? []} getRowKey={(row) => row.move_id}
    loading={loading} error={error} onRetry={() => setRetry((count) => count + 1)}
    initialSort={{ columnId: 'move_date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    onClearFilters={() => {
      const next = new URLSearchParams(params)
      for (const key of [...next.keys()]) if (key === 'net_scope') next.delete(key)
      setParams(next)
    }}
    filterSource={{ id: 'net-change-logs', startDate, endDate }} onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No movements match the selected dates and filters."
    csvFileName={`movement-logs-${startDate}-to-${endDate}.csv`}
    getExportRows={async () => {
      const exported = await getMovements(startDate, endDate, 0, query, true)
      if (exported.items.length !== exported.total) throw new Error('Incomplete movement export')
      return exported.items
    }}
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
          disabled={loading || !!error || disabled} onClick={() => setPage({ queryKey, index })}>
          <span aria-hidden="true">{symbol}</span>
        </button>)}
      </div>
    </nav>}
  />
}
