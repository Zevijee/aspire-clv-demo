import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Table, type TableColumn, type TableQuery } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getPayerChanges, type PayerChange, type PayerChangesPage } from '../api/payerChanges'
import { getPayerChangeLogsFilters } from '../utils/payerChangesDrilldown'
import { formatPayerLos } from '../utils/payerLos'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const columns: TableColumn<PayerChange>[] = [
  { id: 'resident_name', header: 'Resident', isRowHeader: true, filterable: true, value: (row) => row.resident_name },
  { id: 'state', header: 'State', filterable: true, value: (row) => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, value: (row) => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, value: (row) => row.region },
  { id: 'facility_name', header: 'Facility', filterable: true, value: (row) => row.facility_name },
  { id: 'effective_date', header: 'Effective date', value: (row) => row.effective_date,
    format: (_, row) => dateFormat.format(new Date(`${row.effective_date}T00:00:00Z`)) },
  { id: 'previous_payer_type', header: 'Previous payer type', filterable: true, value: (row) => row.previous_payer_type },
  { id: 'previous_payer_name', header: 'Previous payer name', filterable: true, value: (row) => row.previous_payer_name },
  { id: 'new_payer_type', header: 'New payer type', filterable: true, value: (row) => row.new_payer_type },
  { id: 'new_payer_name', header: 'New payer name', filterable: true, value: (row) => row.new_payer_name },
  { id: 'change_category', header: 'Change category', filterable: true, value: (row) => row.change_category },
  { id: 'status', header: 'Status', filterable: true,
    value: (row) => row.status,
    format: (value) => <span className={`payer-status-badge payer-status-badge--${value === 'Ongoing' ? 'ongoing' : 'discharged'}`}>{value}</span> },
  { id: 'previous_los_days', header: 'Previous payer LOS (days)', numeric: true, filterable: true,
    value: (row) => row.previous_los_days,
    format: (value) => formatPayerLos(Number(value)) },
  { id: 'new_los_days', header: 'New payer LOS (days)', numeric: true, filterable: true,
    value: (row) => row.new_los_days,
    format: (value) => formatPayerLos(Number(value)) },

]

export function PayerChangesLogs() {
  const [params] = useSearchParams()
  const initialFilters = getPayerChangeLogsFilters(params)
  return <PayerChangesLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function PayerChangesLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<TableQuery>({ filters: initialFilters, sort: { columnId: 'facility_name', direction: 'ascending' }, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; data: PayerChangesPage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: TableQuery) => {
    setQuery((current) => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getPayerChanges(startDate, endDate, pageIndex * pageSize, query, false, controller.signal)
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
  return <Table<PayerChange>
    title="Payer change logs" subtitle="LOS is time under each payer, in calendar days. Ongoing periods count through today; the date filter selects change events."
    columns={columns} rows={result?.items ?? []} getRowKey={(row) => row.change_id}
    loading={loading} error={error} onRetry={() => setRetry((count) => count + 1)}
    initialSort={{ columnId: 'facility_name', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    onClearFilters={() => {
      const next = new URLSearchParams(params)
      for (const key of [...next.keys()]) if (key.startsWith('logs_')) next.delete(key)
      setParams(next)
    }}
    filterSource={{ id: 'payer-changes', startDate, endDate }} onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No payer changes match the selected dates and filters."
    csvFileName={`payer-change-logs-${startDate}-to-${endDate}.csv`}
    getExportRows={async () => {
      const exported = await getPayerChanges(startDate, endDate, 0, query, true)
      if (exported.items.length !== exported.total) throw new Error('Incomplete payer change export')
      return exported.items
    }}
    footer={<nav aria-label="Payer change log pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} payer changes`
          : error ? 'Pagination unavailable' : 'Loading payer changes…'}
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
