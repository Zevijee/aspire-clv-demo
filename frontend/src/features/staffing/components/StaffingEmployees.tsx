import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  downloadEmployees, employeeScopeParameters, employeesBase, getEmployees, type Employee, type EmployeesPage,
  type EmployeesQuery,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const fixed = (value: number, digits: number) => value.toLocaleString(undefined,
  { minimumFractionDigits: digits, maximumFractionDigits: digits })
const money = (value: number) => `$${fixed(value, 2)}`

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const dollars = (value: number | string) => typeof value === 'number' ? `$${Math.round(value).toLocaleString()}` : value
const tenths = (value: number | string) => typeof value === 'number' ? fixed(value, 1) : value

// Who the employee is and their rate, what they worked, the premiums and
// bonuses on top, and their wages last.
const columns: TableColumn<Employee>[] = [
  { id: 'employee', header: 'Employee', isRowHeader: true, value: row => row.employee_name },
  // Active, or Left with the day they went, as of today.
  { id: 'status', header: 'Status', filterable: true, value: row => row.status,
    format: (_, row) => row.termination_date ? `Left ${day(row.termination_date)}` : row.status },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'department', header: 'Department', filterable: true, value: row => row.department },
  { id: 'role', header: 'Role', filterable: true, value: row => row.role_label },
  { id: 'employment-type', header: 'Type', filterable: true, value: row => row.employment_type },
  // Agency costs more than the facility's own staff: Yes reads red, No green.
  { id: 'agency', header: 'Agency', filterable: true, dataType: 'boolean', negativeWhenTrue: true,
    value: row => row.agency },
  { id: 'hire-date', header: 'Hired', value: row => row.hire_date, format: (_, row) => day(row.hire_date) },
  { id: 'rate', header: 'Avg. hourly rate', numeric: true, value: row => row.avg_rate,
    format: value => typeof value === 'number' ? money(value) : value },
  { id: 'shifts', header: 'Shifts', numeric: true, value: row => row.shifts },
  { id: 'hours', header: 'Hours worked', numeric: true, initialSortDirection: 'descending', value: row => row.hours,
    format: tenths },
  { id: 'hours-per-week', header: 'Hours / week', numeric: true, value: row => row.hours_per_week, format: tenths },
  { id: 'overtime', header: 'Overtime hours', numeric: true, value: row => row.overtime_hours, format: tenths },
  { id: 'overtime-premium', header: 'Overtime premium', numeric: true, value: row => row.overtime_premium,
    format: dollars },
  { id: 'holiday-premium', header: 'Holiday premium', numeric: true, value: row => row.holiday_premium,
    format: dollars },
  { id: 'bonuses', header: 'Bonuses', numeric: true, value: row => row.bonuses, format: dollars },
  { id: 'wages', header: 'Wages', numeric: true, value: row => row.wages, format: dollars },
]

// The overtime window's columns: one row per employee, their overtime added up
// over the range, most first.
const overtimeColumns: TableColumn<Employee>[] = [
  { id: 'employee', header: 'Employee', isRowHeader: true, value: row => row.employee_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'role', header: 'Role', filterable: true, value: row => row.role_label },
  { id: 'employment-type', header: 'Type', filterable: true, value: row => row.employment_type },
  { id: 'shifts', header: 'Shifts', numeric: true, value: row => row.shifts },
  { id: 'hours', header: 'Hours worked', numeric: true, value: row => row.hours, format: tenths },
  { id: 'overtime', header: 'Overtime hours', numeric: true, initialSortDirection: 'descending',
    value: row => row.overtime_hours, format: tenths },
  { id: 'overtime-share', header: 'Overtime share', numeric: true, value: row => row.overtime_share,
    format: value => typeof value === 'number' ? `${fixed(value * 100, 1)}%` : value },
  { id: 'rate', header: 'Avg. hourly rate', numeric: true, value: row => row.avg_rate,
    format: value => typeof value === 'number' ? money(value) : value },
  { id: 'overtime-premium', header: 'Overtime premium', numeric: true, value: row => row.overtime_premium,
    format: dollars },
]

/** The URL parameter another view sets to open the list filtered: a JSON object
 * of column id to selected values, read once and then taken out of the URL. */
export const EMPLOYEE_FILTERS = 'employee_filters'
const FILTER_COLUMNS = ['facility', 'state', 'portfolio', 'region', 'department', 'role', 'employment-type', 'status',
  'agency']

function handedFilters(raw: string | null): Record<string, string[]> {
  if (!raw) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    return Object.fromEntries(Object.entries(parsed).filter(([key, values]) => FILTER_COLUMNS.includes(key)
      && Array.isArray(values) && values.every(value => typeof value === 'string')))
  } catch {
    return {}
  }
}

/** Two sets of filters select the same rows: the same values under each column,
 * whatever their order, with empty selections left out. */
function sameFilters(a: Record<string, string[]>, b: Record<string, string[]>) {
  const key = (filters: Record<string, string[]>) => JSON.stringify(Object.entries(filters)
    .filter(([, values]) => values.length > 0).map(([column, values]) => [column, [...values].sort()])
    .sort(([x], [y]) => String(x).localeCompare(String(y))))
  return key(a) === key(b)
}

/** The Staffing Overview's Employees tab: every employee
 * with hours in the header's date range, paged, sorted and filtered by the API.
 * Each row is one employee's shifts, hours, overtime, hours per patient day at
 * their facility, rate and wages. Only the last 120 days of hours are kept. */
export function StaffingEmployees({ title = 'Employees', fileName = 'staffing-employees', overtime = false,
  roles = [], initialFilters }: {
  /** The table's title, as the tab that shows it names the list. */
  title?: string
  /** The start of the CSV file's name, before the range. */
  fileName?: string
  /** The overtime window's list: only employees with overtime, its columns, most overtime first. */
  overtime?: boolean
  /** The roles to list; empty is every role. */
  roles?: string[]
  /** The table's filters to start with, from whoever opens it; else the URL's. */
  initialFilters?: Record<string, string[]>
}) {
  const [params, setParams] = useReportSearchParams()
  // Filters handed over by a link, such as a role in the Overview's role table:
  // the table starts with them. They stay in the URL, so a remount -- a reload,
  // or a page that mounts twice on a direct visit -- starts with them again,
  // until the person changes the filters; then the URL lets them go.
  const [handed] = useState(() => initialFilters ?? handedFilters(params.get(EMPLOYEE_FILTERS)))
  const scope = { roles, overtimeOnly: overtime }
  const scopeKey = JSON.stringify(scope)
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<EmployeesQuery>({ filters: handed, sort: null, search: '' })
  const queryKey = JSON.stringify([query, startDate, endDate, scopeKey])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; data: EmployeesPage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: EmployeesQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])
  // Filters changed from the ones handed over: the link has done its job.
  useEffect(() => {
    if (!params.has(EMPLOYEE_FILTERS) || sameFilters(query.filters, handed)) return
    const next = new URLSearchParams(params)
    next.delete(EMPLOYEE_FILTERS)
    setParams(next, { replace: true })
  }, [query.filters, handed, params, setParams])

  useEffect(() => {
    const controller = new AbortController()
    void getEmployees(startDate, endDate, pageIndex * pageSize, query, controller.signal, scope)
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
  return <Table<Employee> {...status}
    title={title}
    subtitle={overtime
      ? `Each employee with overtime in the range, their days added up: the hours they worked, the hours over 40 in `
        + `a week, spread over the days worked, and their share, the rate and what time-and-a-half added. ${kept}${clamped}.`
      : `Each employee's hours in the range, from the daily hours of their facility and role. Status says whether `
        + `they still work here today, or the day they left. Overtime is hours `
        + `over 40 in a week; the overtime premium is what those hours paid over straight time, and the holiday premium `
        + `what the hours on paid holidays that were not overtime paid over it, both at time and a half, as the Staffing `
        + `Overview counts them. Bonuses are the shift pickup, 90-day retention and work anniversary bonuses paid `
        + `in the range. Wages are straight time. ${kept}${clamped}.`}
    columns={overtime ? overtimeColumns : columns} rows={result?.items ?? []} getRowKey={row => row.staff_id}
    initialSort={overtime ? { columnId: 'overtime', direction: 'descending' } : { columnId: 'hours', direction: 'descending' }}
    initialFilters={handed}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    // The endpoint carries the scope, so the menus list only what the list can show.
    filterSource={{ id: 'staffing-employees', startDate, endDate,
      endpoint: `${employeesBase}/filter-options?${employeeScopeParameters(scope)}` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No employees match these filters."
    csvFileName={`${fileName}-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadEmployees(startDate, endDate, query, scope)}
    footer={<nav aria-label="Employee pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} employees`
          : error ? 'Pagination unavailable' : 'Loading employees…'}
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
