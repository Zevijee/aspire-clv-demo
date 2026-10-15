import { useCallback, useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import {
  downloadTurnoverPeople, getTurnoverPeople, turnoverPeopleBase, type EmployeesQuery, type TurnoverPeoplePage,
  type TurnoverPerson,
} from '../api'

const pageSize = 50
const day = (value: string) => dayjs(value).format('MMM D, YYYY')

/** How long someone stayed, in months under two years and years after. */
function tenure(days: number) {
  const months = days / 30.44
  return months < 24 ? `${Math.max(0, Math.round(months))} mo` : `${(days / 365.25).toFixed(1)} yrs`
}

const columns: TableColumn<TurnoverPerson>[] = [
  { id: 'employee', header: 'Employee', isRowHeader: true, value: row => row.employee_name },
  { id: 'event', header: 'Event', filterable: true, value: row => row.event },
  { id: 'date', header: 'Date', initialSortDirection: 'descending', value: row => row.date, format: (_, row) => day(row.date) },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'department', header: 'Department', filterable: true, value: row => row.department },
  { id: 'role', header: 'Role', filterable: true, value: row => row.role_label },
  { id: 'employment-type', header: 'Type', filterable: true, value: row => row.employment_type },
  { id: 'hire-date', header: 'Hired', value: row => row.hire_date, format: (_, row) => day(row.hire_date) },
  { id: 'tenure', header: 'Stayed', numeric: true, initialSortDirection: 'descending', value: row => row.tenure_days ?? '',
    format: (_, row) => row.tenure_days === null ? '—' : tenure(row.tenure_days) },
  { id: 'category', header: 'Category', filterable: true, value: row => row.category },
  { id: 'reason', header: 'Reason', filterable: true, truncate: false, value: row => row.reason },
]

/** Everyone hired or leaving in the range, in the roles given and the locations
 * the filters start with: one row per event, paged, sorted and filtered by the
 * API. A departure says how long they stayed and why they left; a hire whom they
 * replaced, or that it was a new position. */
export function TurnoverPeople({ startDate, endDate, roles, initialFilters, fileName }: {
  startDate: string
  endDate: string
  /** The roles to list; empty is every role. */
  roles: string[]
  initialFilters: Record<string, string[]>
  fileName: string
}) {
  const [query, setQuery] = useState<EmployeesQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify([query, startDate, endDate, roles])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; data: TurnoverPeoplePage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: EmployeesQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    void getTurnoverPeople(startDate, endDate, pageIndex * pageSize, query, roles, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message }) })
    return () => controller.abort()
    // requestKey names everything the request reads.
  }, [requestKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const result = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error, onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const scope = new URLSearchParams()
  roles.forEach(role => scope.append('roles', role))
  return <Table<TurnoverPerson> {...status}
    title="Hires and departures"
    subtitle={`The facilities' own employees hired or leaving from ${day(startDate)} to ${day(endDate)}, newest first; `
      + 'agency staff are not counted. A departure says how long they stayed and why they left, voluntary or not; a '
      + 'hire whom they replaced, or that it was a new position. Someone hired and gone in the range has a row for each.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => `${row.staff_id}:${row.event}`}
    initialSort={{ columnId: 'date', direction: 'descending' }} initialFilters={initialFilters}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    // The endpoint carries the roles, so the menus list only what the list can show.
    filterSource={{ id: 'staffing-turnover-people', startDate, endDate,
      endpoint: `${turnoverPeopleBase}/filter-options${scope.size ? `?${scope}` : ''}` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="Nobody was hired or left in this range here."
    csvFileName={`${fileName}.csv`}
    onExport={() => downloadTurnoverPeople(startDate, endDate, query, roles, `${fileName}.csv`)}
    footer={<nav aria-label="Pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} hires and departures`
          : error ? 'Pagination unavailable' : 'Loading…'}
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

/** Turnover and Retention's Logs tab: every hire and departure in the header's
 * date range, every role and location, to filter and search. */
export function TurnoverLogs() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // A new range starts the list afresh: its page, sort and filters.
  return <TurnoverPeople key={`${startDate}:${endDate}`} startDate={startDate} endDate={endDate} roles={[]}
    initialFilters={{}} fileName={`turnover-logs-${startDate}-to-${endDate}`} />
}

/** What a clicked name or figure in Turnover and Retention stands for: its row's
 * roles and locations, and, for a Hires or Departures figure, that event only. */
export type TurnoverWindow = { name: string; roles: string[]; filters: Record<string, string[]> }

/** The people behind a row of Turnover and Retention, in a window over the page. */
export function TurnoverPeopleModal({ scope, startDate, endDate, onClose }: {
  scope: TurnoverWindow | null
  startDate: string
  endDate: string
  onClose: () => void
}) {
  return <FullScreenModal open={scope !== null} onClose={onClose} destroyOnHidden
    title={scope ? `Hires and departures · ${scope.name}` : ''}>
    {scope && <div className="net-change-daily-modal__table">
      <TurnoverPeople startDate={startDate} endDate={endDate} roles={scope.roles} initialFilters={scope.filters}
        fileName={`turnover-people-${startDate}-to-${endDate}`} />
    </div>}
  </FullScreenModal>
}
