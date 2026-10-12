import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  agencyLogsBase, downloadAgencyLogs, getAgencyLogs, type AgencyLogsPage, type AgencyShift, type EmployeesQuery,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const weekdayFormat = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const weekday = (value: string) => weekdayFormat.format(new Date(`${value}T00:00:00Z`))
const fixed = (value: number, digits: number) => value.toLocaleString(undefined,
  { minimumFractionDigits: digits, maximumFractionDigits: digits })
const money = (value: number) => `$${fixed(value, 2)}`

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<AgencyShift>[] = [
  { id: 'date', header: 'Date', isRowHeader: true, initialSortDirection: 'descending', value: row => row.work_date,
    format: (_, row) => weekday(row.work_date) },
  { id: 'employee', header: 'Agency staff', value: row => row.employee_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'role', header: 'Role', filterable: true, value: row => row.role_label },
  { id: 'first-day', header: 'First day', value: row => row.hire_date, format: (_, row) => day(row.hire_date),
    sortable: false },
  { id: 'hours', header: 'Hours', numeric: true, value: row => row.hours,
    format: value => typeof value === 'number' ? fixed(value, 1) : value },
  { id: 'rate', header: 'Hourly rate', numeric: true, value: row => row.rate,
    format: value => typeof value === 'number' ? money(value) : value },
  { id: 'wages', header: 'Wages', numeric: true, value: row => row.wages,
    format: value => typeof value === 'number' ? money(value) : value },
]

/** Agency vs In-house's Logs tab: one row per agency person per day worked in
 * the header's date range, paged, sorted and filtered by the API: who, where,
 * the hours, the rate and the wages. Only the last 120 days of hours are kept. */
export function AgencyLogs() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // Every role, as PPD's Employees tab: the table's own Role filter narrows.
  const roles: string[] = []
  const roleName = 'every role'
  const [query, setQuery] = useState<EmployeesQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify([query, startDate, endDate, roles])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; data: AgencyLogsPage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: EmployeesQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getAgencyLogs(startDate, endDate, roles, pageIndex * pageSize, query, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
    // requestKey names everything the request reads.
  }, [requestKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const result = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const kept = result ? `Hours are kept for the last 120 days, ${day(result.available_from)} to ${day(result.available_through)}` : ''
  const clamped = result && (result.start_date !== startDate || result.end_date !== endDate)
    ? `; showing ${day(result.start_date)} to ${day(result.end_date)}` : ''
  return <>
    <Table<AgencyShift> {...status}
    title="Agency shifts"
    subtitle={`Each day an agency person worked in the range, ${roleName}: where, in which role, for how many hours `
      + `and at what rate, from the daily hours of their facility and role. ${kept}${clamped}.`}
    columns={columns} rows={result?.items ?? []} getRowKey={row => `${row.work_date}:${row.staff_id}`}
    initialSort={{ columnId: 'date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'staffing-agency-logs', startDate, endDate, endpoint: `${agencyLogsBase}/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No agency shifts match these filters."
    csvFileName={`agency-shifts-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadAgencyLogs(startDate, endDate, roles, query)}
    footer={<nav aria-label="Agency shift pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} shifts`
          : error ? 'Pagination unavailable' : 'Loading shifts…'}
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
  </>
}
