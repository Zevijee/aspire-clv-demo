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

// --- Agency vs In-house ------------------------------------------------------

/** One role's hours and wages at one facility over the range, split by who
 * worked them, to add up and divide once. */
export type RoleSplit = {
  agency_hours: number
  // The agency rate is agency_wages / agency_hours.
  agency_wages: number
  inhouse_hours: number
  // The in-house rate is inhouse_wages / inhouse_hours.
  inhouse_wages: number
  // What the agency hours cost over the same hours at this facility and role's
  // in-house rate. Additive: a scope's premium is its facilities' summed.
  agency_premium: number
}

export type FacilityAgency = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  roles: Record<string, RoleSplit>
}

export type AgencyReport = {
  // The range shown: the request clamped to the days kept.
  start_date: string
  end_date: string
  // The first and last days with hours: only the last 120 days are kept.
  available_from: string
  available_through: string
  items: FacilityAgency[]
}

export function getAgency(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<AgencyReport>(`${base}/api/v1/staffing/agency?${params}`, signal)
}

/** One facility's agency hours, in-house hours and agency wages for each day
 * of the range, aligned to the response's dates, to add up day by day. */
export type FacilityAgencyTrend = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  agency_hours: number[]
  inhouse_hours: number[]
  agency_wages: number[]
}

export type AgencyTrend = {
  start_date: string
  end_date: string
  available_from: string
  available_through: string
  dates: string[]
  items: FacilityAgencyTrend[]
}

// The Agency vs In-house role picker, kept in the URL so every tab shares it;
// empty means every role.
export const AGENCY_ROLE_PARAM = 'agency_role'

export function getAgencyTrend(startDate: string, endDate: string, roles: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  roles.forEach(role => params.append('roles', role))
  return readJson<AgencyTrend>(`${base}/api/v1/staffing/agency/trend?${params}`, signal)
}

export const agencyLogsBase = `${base}/api/v1/staffing/agency/logs`

/** One agency person on one day: who, where, how long and what it cost. */
export type AgencyShift = {
  work_date: string
  staff_id: string
  employee_name: string
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  role: string
  role_label: string
  hire_date: string
  hours: number
  // Wages over hours.
  rate: number
  wages: number
}

export type AgencyLogsPage = {
  items: AgencyShift[]
  total: number
  start_date: string
  end_date: string
  available_from: string
  available_through: string
}

/** The request's parameters: the range and the table's filters, search and
 * sort. Shared by the page, its filter menus and the CSV. */
export function agencyLogParameters(startDate: string, endDate: string, roles: string[], query: EmployeesQuery,
    offset = 0) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: '50',
    offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'date', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
  roles.forEach(role => params.append('roles', role))
  return params
}

export function getAgencyLogs(startDate: string, endDate: string, roles: string[], offset: number,
    query: EmployeesQuery, signal?: AbortSignal) {
  return readJson<AgencyLogsPage>(
    `${agencyLogsBase}?${agencyLogParameters(startDate, endDate, roles, query, offset)}`, signal)
}

export async function downloadAgencyLogs(startDate: string, endDate: string, roles: string[], query: EmployeesQuery) {
  const response = await authorizedFetch(
    `${agencyLogsBase}/export?${agencyLogParameters(startDate, endDate, roles, query)}`)
  if (!response.ok) throw new Error('Agency shift export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `agency-shifts-${startDate}-to-${endDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
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

// --- Overtime ----------------------------------------------------------------

// The Overtime report's role picker, kept in the URL so every tab shares it;
// empty means every role.
export const OVERTIME_ROLE_PARAM = 'overtime_role'

/** One role's hours, overtime and people at one facility over the range, to
 * add up and divide once. */
export type RoleOvertime = {
  hours: number
  // The average rate is wages / hours.
  wages: number
  // Hours over the weekly line per person, summed.
  overtime_hours: number
  // Straight-time pay of the overtime hours: the premium is `premium` x this.
  overtime_wages: number
  // Person-days with any overtime.
  overtime_shifts: number
}

export type FacilityOvertime = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  roles: Record<string, RoleOvertime>
}

export type OvertimeReport = {
  start_date: string
  end_date: string
  available_from: string
  available_through: string
  // The weekly line overtime is counted above, and what an overtime hour
  // costs over straight time as a share of its pay.
  weekly_hours: number
  premium: number
  items: FacilityOvertime[]
}

export function getOvertime(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<OvertimeReport>(`${base}/api/v1/staffing/overtime?${params}`, signal)
}

/** One facility's hours, overtime hours and the overtime's straight-time pay
 * for each day of the range, aligned to the response's dates. */
export type FacilityOvertimeTrend = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  hours: number[]
  overtime_hours: number[]
  overtime_wages: number[]
}

export type OvertimeTrend = {
  start_date: string
  end_date: string
  available_from: string
  available_through: string
  dates: string[]
  items: FacilityOvertimeTrend[]
}

export function getOvertimeTrend(startDate: string, endDate: string, roles: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  roles.forEach(role => params.append('roles', role))
  return readJson<OvertimeTrend>(`${base}/api/v1/staffing/overtime/trend?${params}`, signal)
}

export const overtimeLogsBase = `${base}/api/v1/staffing/overtime/logs`

/** One person on one day with overtime: who, where, how much of the day was
 * over the line and what it cost. */
export type OvertimeShift = {
  work_date: string
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
  hours: number
  overtime_hours: number
  rate: number
  // What time-and-a-half would add.
  premium: number
}

export type OvertimeLogsPage = {
  items: OvertimeShift[]
  total: number
  start_date: string
  end_date: string
  available_from: string
  available_through: string
}

export function overtimeLogParameters(startDate: string, endDate: string, roles: string[], query: EmployeesQuery,
    offset = 0) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: '50',
    offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'date', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
  roles.forEach(role => params.append('roles', role))
  return params
}

export function getOvertimeLogs(startDate: string, endDate: string, roles: string[], offset: number,
    query: EmployeesQuery, signal?: AbortSignal) {
  return readJson<OvertimeLogsPage>(
    `${overtimeLogsBase}?${overtimeLogParameters(startDate, endDate, roles, query, offset)}`, signal)
}

export async function downloadOvertimeLogs(startDate: string, endDate: string, roles: string[], query: EmployeesQuery) {
  const response = await authorizedFetch(
    `${overtimeLogsBase}/export?${overtimeLogParameters(startDate, endDate, roles, query)}`)
  if (!response.ok) throw new Error('Overtime export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `overtime-shifts-${startDate}-to-${endDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
