import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// shared/staffing.py ROLES, in report order; the API names the same codes.
export const STAFFING_ROLES = [
  { value: 'rn', label: 'RN', context: 'Nursing' },
  { value: 'lpn', label: 'LPN', context: 'Nursing' },
  { value: 'cna', label: 'CNA', context: 'Nursing' },
  { value: 'pt', label: 'PT', context: 'Therapy' },
  { value: 'pta', label: 'PTA', context: 'Therapy' },
  { value: 'ot', label: 'OT', context: 'Therapy' },
  { value: 'cota', label: 'COTA', context: 'Therapy' },
  { value: 'slp', label: 'SLP', context: 'Therapy' },
  { value: 'dietary_aide', label: 'Dietary Aide', context: 'Support' },
  { value: 'cook', label: 'Cook', context: 'Support' },
  { value: 'evs', label: 'EVS', context: 'Support' },
]

/** One role's sums at one facility over the range, to add up and divide once. */
export type RoleHours = {
  hours: number
  // Target PPD x each day's census, summed.
  target_hours: number
  // Hours over each day's target, summed over days.
  excess_hours: number
  short_hours: number
  // Pay for the hours worked: the average rate is wages / hours.
  wages: number
  // The excess hours at each day's rate.
  excess_wages: number
}

export type FacilityStaffing = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Closing census summed over the range: PPD divides by it.
  census_days: number
  roles: Record<string, RoleHours>
}

export type PpdReport = { start_date: string; end_date: string; items: FacilityStaffing[] }

export function getPpd(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<PpdReport>(`${base}/api/v1/staffing/ppd?${params}`, signal)
}

// --- Trending ----------------------------------------------------------------

// The Trending tab's role picker, kept in the URL; empty means every role the
// header's Roles filter allows.
export const TREND_ROLE_PARAM = 'trend_role'

/** One facility's hours, target hours and census for each day of the range,
 * aligned to the response's dates, to add up and divide day by day. */
export type FacilityTrend = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  hours: number[]
  target_hours: number[]
  census: number[]
}

export type PpdTrend = { start_date: string; end_date: string; dates: string[]; items: FacilityTrend[] }

export function getPpdTrend(startDate: string, endDate: string, roles: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  roles.forEach(role => params.append('roles', role))
  return readJson<PpdTrend>(`${base}/api/v1/staffing/ppd/trend?${params}`, signal)
}

// --- Employees ---------------------------------------------------------------

export const employeesBase = `${base}/api/v1/staffing/employees`

export type EmployeesQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

/** One staff member with hours in the range: their sums, and the ratios the
 * API divided once. */
export type Employee = {
  staff_id: string
  employee_name: string
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  role: string
  role_label: string
  employment_type: string
  hire_date: string
  // Days worked in the range.
  shifts: number
  hours: number
  // Hours over shifts.
  avg_shift: number
  // Hours over the weeks in the range.
  hours_per_week: number
  // Hours over 40 in a week, summed over the range's weeks.
  overtime_hours: number
  // The facility's closing census summed over the range: PPD divides by it.
  census_days: number
  // The employee's hours per patient day at their facility.
  ppd: number | null
  // Wages over hours.
  avg_rate: number
  wages: number
}

export type EmployeesPage = {
  items: Employee[]
  total: number
  // The range the page covers: the request's, clamped to the days kept.
  start_date: string
  end_date: string
  // The first and last days with hours: only the last 120 days are kept.
  available_from: string
  available_through: string
}

/** The request's parameters: the range and the table's filters, search and
 * sort. Shared by the page, its filter menus and the CSV. */
export function employeeParameters(startDate: string, endDate: string, query: EmployeesQuery, offset = 0) {
  return new URLSearchParams({ start_date: startDate, end_date: endDate, limit: '50',
    offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'hours', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getEmployees(startDate: string, endDate: string, offset: number, query: EmployeesQuery,
    signal?: AbortSignal) {
  return readJson<EmployeesPage>(`${employeesBase}?${employeeParameters(startDate, endDate, query, offset)}`, signal)
}

export async function downloadEmployees(startDate: string, endDate: string, query: EmployeesQuery) {
  const response = await authorizedFetch(`${employeesBase}/export?${employeeParameters(startDate, endDate, query)}`)
  if (!response.ok) throw new Error('Employee export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `ppd-employees-${startDate}-to-${endDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
