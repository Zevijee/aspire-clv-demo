import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// shared/staffing.py ROLES, in report order; the API names the same codes.
// `context` is the role's department, which the role tables and pickers group by.
export const STAFFING_ROLES = [
  { value: 'administrator', label: 'Administrator', context: 'Admin & General' },
  { value: 'business_office_manager', label: 'Business Office Manager', context: 'Admin & General' },
  { value: 'hr_payroll', label: 'HR/Payroll', context: 'Admin & General' },
  { value: 'rn', label: 'RN', context: 'Direct Care' },
  { value: 'lpn', label: 'LPN', context: 'Direct Care' },
  { value: 'lpn_supervisor', label: 'LPN Supervisor', context: 'Direct Care' },
  { value: 'lpn_wound_nurse', label: 'LPN Wound Nurse', context: 'Direct Care' },
  { value: 'cna', label: 'CNA', context: 'Direct Care' },
  { value: 'ncna', label: 'NCNA', context: 'Direct Care' },
  { value: 'cma', label: 'CMA', context: 'Direct Care' },
  { value: 'cook', label: 'Cook', context: 'Non-Nursing' },
  { value: 'dietary_aide', label: 'Dietary Aide', context: 'Non-Nursing' },
  { value: 'dietary_manager', label: 'Dietary Manager', context: 'Non-Nursing' },
  { value: 'dietician', label: 'Dietician', context: 'Non-Nursing' },
  { value: 'housekeeper', label: 'Housekeeper', context: 'Non-Nursing' },
  { value: 'housekeeping_director', label: 'Housekeeping Director', context: 'Non-Nursing' },
  { value: 'laundry_aide', label: 'Laundry Aide', context: 'Non-Nursing' },
  { value: 'maintenance_director', label: 'Maintenance Director', context: 'Non-Nursing' },
  { value: 'social_services_director', label: 'Social Services Director', context: 'Non-Nursing' },
  { value: 'transportation_driver', label: 'Transportation/Driver', context: 'Non-Nursing' },
  { value: 'adon_lpn', label: 'ADON LPN', context: 'Nursing Admin' },
  { value: 'mds_rn', label: 'MDS RN', context: 'Nursing Admin' },
  { value: 'staffing_coordinator', label: 'Certified Staffing Coordinator (CNA)', context: 'Nursing Admin' },
]

// The departments roles belong to: each role's `context`, in report order.
export const STAFFING_DEPARTMENTS = ['Admin & General', 'Direct Care', 'Non-Nursing', 'Nursing Admin']

/** One role's sums at one facility over the range, to add up and divide once. */
export type RoleHours = {
  hours: number
  // Target HPPD x each day's census, summed.
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
  // Closing census summed over the range: HPPD divides by it.
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

/** One facility's labour cost, budget and census for each day of the range,
 * aligned to the response's dates, for PPD cost's Trending tab. */
export type FacilityCostTrend = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Total labour cost: straight time plus the agency, overtime and holiday
  // premiums, orientation, training and sign-on bonuses.
  cost: number[]
  // Target hours at each role's straight-time rate that day.
  budget: number[]
  census: number[]
}

export type PpdCostTrend = { start_date: string; end_date: string; dates: string[]; items: FacilityCostTrend[] }

export function getPpdCostTrend(startDate: string, endDate: string, roles: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  roles.forEach(role => params.append('roles', role))
  return readJson<PpdCostTrend>(`${base}/api/v1/staffing/ppd-cost/trend?${params}`, signal)
}

// --- Employees ---------------------------------------------------------------

/** Every employee of a range, compactly: what a Staffing Overview export carries. */
export type PackedEmployees = {
  start_date: string
  end_date: string
  weeks: number
  overtime_premium: number
  facilities: string[][]
  roles: Record<string, string[]>
  rows: (string | number)[][]
}

export function getEmployeesPacked(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<PackedEmployees>(`${base}/api/v1/staffing/employees/packed?${params}`, signal)
}

export const employeesBase = `${base}/api/v1/staffing/employees`

export type EmployeesQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

/** One employee with hours in the range: their sums, and the ratios the
 * API divided once. */
export type Employee = {
  staff_id: string
  employee_name: string
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // The role's department: Admin & General, Direct Care, Non-Nursing or Nursing Admin.
  department: string
  role: string
  role_label: string
  employment_type: string
  // Active, or Left once their termination date has passed.
  status: string
  // The day they left; null while they work here.
  termination_date: string | null
  // Yes for agency staff, No for the facility's own employees.
  agency: string
  hire_date: string
  // Days worked in the range.
  shifts: number
  hours: number
  // Hours over shifts.
  avg_shift: number
  // Hours over the weeks in the range.
  hours_per_week: number
  // Overtime hours over hours worked.
  overtime_share: number
  // Hours over 40 in a week, spread over the days worked, summed over the range.
  overtime_hours: number
  // The facility's closing census summed over the range: HPPD divides by it.
  census_days: number
  // The employee's hours per patient day at their facility.
  ppd: number | null
  // Wages over hours.
  avg_rate: number
  wages: number
  // What the overtime hours paid over straight time.
  overtime_premium: number
  // What the hours on paid holidays that were not overtime paid over straight time.
  holiday_premium: number
  // The shift pickup, 90-day retention and anniversary bonuses paid in the range.
  bonuses: number
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
/** Which employees: some roles only (empty is every role), and only those with
 * overtime in the range. Sent with the page, its menus and the CSV alike. */
export type EmployeesScope = { roles?: string[]; overtimeOnly?: boolean }

export function employeeScopeParameters({ roles = [], overtimeOnly = false }: EmployeesScope = {}) {
  const params = new URLSearchParams()
  roles.forEach(role => params.append('roles', role))
  if (overtimeOnly) params.set('overtime_only', 'true')
  return params
}

export function employeeParameters(startDate: string, endDate: string, query: EmployeesQuery, offset = 0,
    scope: EmployeesScope = {}) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: '50',
    offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'hours', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
  employeeScopeParameters(scope).forEach((value, key) => params.append(key, value))
  return params
}

export function getEmployees(startDate: string, endDate: string, offset: number, query: EmployeesQuery,
    signal?: AbortSignal, scope: EmployeesScope = {}) {
  return readJson<EmployeesPage>(`${employeesBase}?${employeeParameters(startDate, endDate, query, offset, scope)}`,
    signal)
}

export async function downloadEmployees(startDate: string, endDate: string, query: EmployeesQuery,
    scope: EmployeesScope = {}) {
  const response = await authorizedFetch(
    `${employeesBase}/export?${employeeParameters(startDate, endDate, query, 0, scope)}`)
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
  // Hours over the weekly line per employee, summed.
  overtime_hours: number
  // Straight-time pay of the overtime hours: the premium is `premium` x this.
  overtime_wages: number
  // Employee-days with any overtime.
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

/** One employee on one day with overtime: who, where, how much of the day was
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

// --- Overview ----------------------------------------------------------------

/** One role's sums at one facility over the range, to add up and divide once at
 * any drilldown level, for any set of roles. Every field is additive. */
export type RoleOverview = {
  // Hours worked: the hours HPPD counts.
  hours: number
  // Budget: target HPPD x census, each day.
  target_hours: number
  excess_hours: number
  // Straight-time pay for the hours worked at each day's in-house rate.
  wages: number
  // The hours over each day's budget at that rate.
  excess_wages: number
  overtime_hours: number
  // Straight-time pay of the overtime hours.
  overtime_wages: number
  // Hours on a paid holiday that were not overtime, and their straight-time pay.
  holiday_hours: number
  holiday_wages: number
  agency_hours: number
  // What the agency hours cost over the in-house rate, as Agency vs In-house prices it.
  agency_premium: number
  new_hires: number
  // Paid orientation, in the classroom and on the floor shadowing a preceptor:
  // in total hours and cost, never in hours worked or HPPD.
  classroom_orientation_hours: number
  classroom_orientation_wages: number
  floor_orientation_hours: number
  floor_orientation_wages: number
  // The calendar days the hires took to finish classroom, then floor,
  // orientation, summed over them: the average is these over new_hires.
  classroom_orientation_days: number
  floor_orientation_days: number
  bonuses: number
  // What the agency hours were paid: the agency rate is this over agency_hours.
  agency_wages: number
  // Hours worked by the facility's own employees.
  inhouse_hours: number
  // In-service training: paid like orientation, in total hours and cost, never in HPPD.
  training_hours: number
  training_wages: number
}

export type FacilityOverview = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Closing census summed over the range, once per facility: HPPD for any set
  // of roles divides by it.
  census_days: number
  roles: Record<string, RoleOverview>
}

export type StaffingOverview = {
  start_date: string
  end_date: string
  days: number
  holidays: string[]
  // What an overtime or holiday hour pays over straight time, as a share of its pay.
  overtime_premium: number
  holiday_premium: number
  items: FacilityOverview[]
}

// The response as sent: each role's measures an array in `measures` order,
// which is a third the size of 5,566 objects with named fields.
type StaffingOverviewResponse = Omit<StaffingOverview, 'items'> & {
  measures: (keyof RoleOverview)[]
  items: (Omit<FacilityOverview, 'roles'> & { roles: Record<string, number[]> })[]
}

export async function getStaffingOverview(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const body = await readJson<StaffingOverviewResponse>(`${base}/api/v1/staffing/overview?${params}`, signal)
  const { measures, items, ...rest } = body
  return {
    ...rest,
    items: items.map(item => ({ ...item, roles: Object.fromEntries(Object.entries(item.roles).map(([code, values]) =>
      [code, Object.fromEntries(measures.map((measure, index) => [measure, values[index]])) as RoleOverview])) })),
  } as StaffingOverview
}

// --- Monthly Staffing Trending -----------------------------------------------

export type MonthlyStaffingFacility = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Each by YYYY-MM: closing census summed over the month, once per facility,
  // and the hours worked, budget hours and labour cost of the roles asked for,
  // the cost as the PPD cost report counts it.
  census_days: Record<string, number>
  hours: Record<string, number>
  // Of the hours worked, those worked by agency employees, and those over 40 in
  // an employee's week.
  agency_hours: Record<string, number>
  overtime_hours: Record<string, number>
  target_hours: Record<string, number>
  cost: Record<string, number>
  // The premiums and extras: the hours over each day's budget at straight time,
  // what agency hours cost over the in-house rate, and what overtime paid over
  // straight time.
  excess_wages: Record<string, number>
  agency_premium: Record<string, number>
  overtime_premium: Record<string, number>
  // Sign-on bonuses, and the new hires they were paid to.
  bonuses: Record<string, number>
  new_hires: Record<string, number>
  // The facility's own employees, from the roster: headcount at the month's
  // start and end, its hires and departures, and those employed at its start
  // still there at its end.
  headcount_start: Record<string, number>
  headcount_end: Record<string, number>
  hires: Record<string, number>
  departures: Record<string, number>
  retained: Record<string, number>
}

export type MonthlyStaffing = {
  start: string
  // The last day read: the end of the last month, or the latest generated day.
  end: string
  months: { month: string; days: number; month_days: number }[]
  items: MonthlyStaffingFacility[]
}

type MonthlyMeasure = Exclude<keyof MonthlyStaffingFacility, 'facility_id' | 'facility_name' | 'state' | 'portfolio'
  | 'region'>

// The response as sent: each facility's measures as arrays aligned to `months`,
// in `measures` order -- half the size of a dict per measure keyed by month.
type MonthlyStaffingResponse = Omit<MonthlyStaffing, 'items'> & {
  measures: MonthlyMeasure[]
  items: (Pick<MonthlyStaffingFacility, 'facility_id' | 'facility_name' | 'state' | 'portfolio' | 'region'>
    & { values: number[][] })[]
}

// Every tab asks for the same months, so each answer is kept a while and shared:
// switching tabs, or back, does not wait for the API again. Kept for minutes
// only, as the midnight update adds a day, and only the last few ranges.
const MONTHLY_KEEP_MS = 5 * 60_000
const MONTHLY_KEEP = 6
const monthlyAnswers = new Map<string, { at: number; answer: Promise<MonthlyStaffing> }>()

/** Every facility's census days, hours, labour cost and premiums by month, over
 * `roles`; none is every role. Shared between callers: a caller that leaves
 * ignores the answer rather than cancelling it, so the next one can use it. */
export function getMonthlyStaffing(startMonth: string, endMonth: string, roles: string[]) {
  const params = new URLSearchParams({ start_month: startMonth, end_month: endMonth })
  roles.forEach(role => params.append('roles', role))
  const url = `${base}/api/v1/staffing/monthly-trending?${params}`
  const kept = monthlyAnswers.get(url)
  if (kept && Date.now() - kept.at < MONTHLY_KEEP_MS) return kept.answer
  const answer = readJson<MonthlyStaffingResponse>(url).then(({ measures, items, ...rest }) => ({
    ...rest,
    items: items.map(({ values, ...item }) => {
      const facility = { ...item } as MonthlyStaffingFacility
      measures.forEach((measure, index) => {
        // Months with none are left out, as absence means zero.
        const byMonth: Record<string, number> = {}
        values[index].forEach((value, at) => { if (value) byMonth[rest.months[at].month] = value })
        facility[measure] = byMonth
      })
      return facility
    }),
  }))
  answer.catch(() => monthlyAnswers.delete(url))
  monthlyAnswers.delete(url)
  monthlyAnswers.set(url, { at: Date.now(), answer })
  while (monthlyAnswers.size > MONTHLY_KEEP) monthlyAnswers.delete(monthlyAnswers.keys().next().value!)
  return answer
}

// --- Turnover and Retention --------------------------------------------------

/** One role's counts at a facility over the range. */
export type RoleTurnover = {
  // Employed the day before the range, and on its last day.
  start_headcount: number
  end_headcount: number
  hires: number
  departures: number
  // Employed both before the range and on its last day.
  retained: number
  // Hires whose 90th day fell in the range, and those of them still employed on it.
  eligible_90: number
  retained_90: number
  // The end headcount's days since hire, summed.
  tenure_days: number
}

export type FacilityTurnover = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  roles: Record<string, RoleTurnover>
}

export type TurnoverReport = {
  start_date: string
  end_date: string
  days: number
  items: FacilityTurnover[]
}

type TurnoverResponse = Omit<TurnoverReport, 'items'> & {
  measures: (keyof RoleTurnover)[]
  items: (Omit<FacilityTurnover, 'roles'> & { roles: Record<string, number[]> })[]
}

/** Every facility's own employees between the dates, per role, as arrays decoded to named counts. */
export async function getTurnover(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const { measures, items, ...rest } = await readJson<TurnoverResponse>(`${base}/api/v1/staffing/turnover?${params}`,
    signal)
  return {
    ...rest,
    items: items.map(item => ({ ...item, roles: Object.fromEntries(Object.entries(item.roles).map(([code, values]) =>
      [code, Object.fromEntries(measures.map((measure, index) => [measure, values[index]])) as RoleTurnover])) })),
  } as TurnoverReport
}

/** One hire or departure in the range: who, where, when, and why they left or
 * whom they replaced. */
export type TurnoverPerson = {
  staff_id: string
  event: 'Hired' | 'Left'
  date: string
  employee_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  department: string
  role: string
  role_label: string
  employment_type: string
  hire_date: string
  termination_date: string | null
  // For a departure, the days from hire to leaving.
  tenure_days: number | null
  // Voluntary or Involuntary for a departure; Replacement or New position for a hire.
  category: string
  reason: string
}

export type TurnoverPeoplePage = { items: TurnoverPerson[]; total: number; limit: number; offset: number }

export const turnoverPeopleBase = `${base}/api/v1/staffing/turnover/people`

function turnoverPeopleParameters(startDate: string, endDate: string, query: EmployeesQuery, offset: number,
    roles: string[]) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'date', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
  roles.forEach(role => params.append('roles', role))
  return params
}

export function getTurnoverPeople(startDate: string, endDate: string, offset: number, query: EmployeesQuery,
    roles: string[], signal?: AbortSignal) {
  return readJson<TurnoverPeoplePage>(
    `${turnoverPeopleBase}?${turnoverPeopleParameters(startDate, endDate, query, offset, roles)}`, signal)
}

export async function downloadTurnoverPeople(startDate: string, endDate: string, query: EmployeesQuery,
    roles: string[], fileName: string) {
  const response = await authorizedFetch(
    `${turnoverPeopleBase}/export?${turnoverPeopleParameters(startDate, endDate, query, 0, roles)}`)
  if (!response.ok) throw new Error('The export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- PBJ Compliance ----------------------------------------------------------

/** One facility's PBJ quarter: resident days, each PBJ role's hours, its RN
 * coverage and its 12-month turnover. */
export type FacilityPbj = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Days with residents, closing census summed, and the same over weekends.
  days: number
  resident_days: number
  weekend_resident_days: number
  // Each PBJ role's [hours, weekend hours, agency hours].
  roles: Record<string, [number, number, number]>
  days_without_rn: number
  days_under_8_rn: number
  // [nurse departures, nurse headcount at the start, at the end, RN departures,
  // RN headcount at the start, at the end, administrator departures].
  turnover: number[]
}

export type PbjReport = {
  start_date: string
  end_date: string
  due_date: string
  // Each role's PBJ job title code.
  codes: Record<string, number>
  items: FacilityPbj[]
}

export function getPbj(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<PbjReport>(`${base}/api/v1/staffing/pbj?${params}`, signal)
}
