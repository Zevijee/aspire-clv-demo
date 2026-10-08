import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export const medicareBase = `${base}/api/v1/mds/current-medicare`

export type MedicareResidentsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type MedicareResident = {
  stay_id: string
  resident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  payer_type: string
  payer_name: string
  admission_date: string
  // Days since admission.
  length_of_stay: number
  // The 5-day assessment's reference date; null until it is coded.
  ard: string | null
  // Four-letter PDPM code: PT/OT, SLP, nursing and NTA case-mix groups.
  pdpm_score: string
  // Total revenue over the days on this payer.
  average_rate: number
  // PDPM revenue on this payer through the census day.
  total_revenue: number
}

export type MedicareResidentsPage = {
  items: MedicareResident[]; total: number; limit: number; offset: number; census_date: string
}

function residentParameters(query: MedicareResidentsQuery, offset = 0) {
  return new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident',
    direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getMedicareResidents(offset: number, query: MedicareResidentsQuery, signal?: AbortSignal) {
  return readJson<MedicareResidentsPage>(`${medicareBase}/residents?${residentParameters(query, offset)}`, signal)
}

export async function downloadMedicareResidents(query: MedicareResidentsQuery, censusDate: string) {
  const response = await authorizedFetch(`${medicareBase}/residents/export?${residentParameters(query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `current-medicare-residents-${censusDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type PrimaryDiagnosis = {
  major_joint: number
  ortho: number
  acute_neuro: number
  medical_management: number
}

export type PtOt = {
  score_0_5: number
  score_6_9: number
  score_10_23: number
  score_24: number
}

// Residents with each SLP condition. These overlap -- one resident can have
// several -- so they do not sum to the residents.
export type Speech = {
  cognitive_impairment: number
  acute_neuro: number
  mechanically_altered_diet: number
  swallowing_disorder: number
  slp_comorbidity: number
}

// PDPM residents per SLP group, the second letter of the code: speech_N_swallowing_M
// for N speech conditions (0-3) and M swallowing needs (0-2). Exactly one each.
export type Slp = Record<string, number>

// PDPM residents per nursing function score band, from the score on the assessment.
export type Nursing = {
  score_0_5: number
  score_6_14: number
  score_15_16: number
}

// PDPM residents per NTA comorbidity points band, the fourth letter of the code:
// points_0, points_1_2, points_3_5, points_6_8, points_9_11, points_12_plus.
export type Nta = Record<string, number>

// PDPM residents with and without signs of depression, from the assessment flag.
export type Depression = { yes: number; no: number }

export type FacilityCategories = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // PDPM residents per PT/OT clinical category, the first letter of the code.
  primary_diagnosis: PrimaryDiagnosis
  // The same residents per PT/OT function score band, from the same letter.
  pt_ot: PtOt
  slp: Slp
  nursing: Nursing
  // PDPM residents per nursing clinical category (extensive_services, ...),
  // the third letter of the code.
  nursing_category: Record<string, number>
  nta: Nta
  depression: Depression
  speech: Speech
  // PDPM residents whose code is not available yet: not assessed and coded in
  // the first days of their Medicare period. Counted in no category.
  no_score: number
  // Their days since admission, summed: divide by no_score at any scope.
  no_score_days: number
}

export type CategoriesReport = { census_date: string; items: FacilityCategories[] }

/** A facility's PDPM category counts alone, whichever residents or stays they count. */
export type CategoryCounts = Omit<FacilityCategories, 'facility_id' | 'facility_name' | 'state' | 'portfolio' | 'region'>

export function getMedicareCategories(signal?: AbortSignal) {
  return readJson<CategoriesReport>(`${base}/api/v1/mds/current-medicare/categories`, signal)
}

export type FacilityMedicare = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // PDPM residents on the census day: Original Medicare, and Medicare
  // Advantage on a PDPM contract. Per diem contract residents are not included.
  federal: number
  managed: number
  // Sums, never averages: add them up for a scope, then divide once by its
  // residents, so every average is weighted by who is in the beds.
  actual_rates: number
  neutral_rates: number
  resident_days: number
}

export type CurrentMedicareReport = {
  as_of: string
  census_date: string
  neutral_per_diem: number
  items: FacilityMedicare[]
  data_status: { available_from: string | null; available_through: string | null; generated_at: string | null }
}

export function getCurrentMedicare(signal?: AbortSignal) {
  return readJson<CurrentMedicareReport>(`${base}/api/v1/mds/current-medicare`, signal)
}

export type FacilityHistorical = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Medicare PDPM stays whose start (or ARD) falls in the range: Original
  // Medicare, and Medicare Advantage on a PDPM contract.
  federal: number
  managed: number
  // Sums, never averages: add them up for a scope, then divide once -- days by
  // stays for length of stay, revenue by days for a rate.
  medicare_days: number
  actual_revenue: number
  neutral_revenue: number
  // Those stays' days in a bed inside the range: the trend's census summed.
  census_days: number
}

export type HistoricalMedicareReport = {
  start_date: string
  end_date: string
  date_basis: 'start' | 'ard'
  // Stays still running are counted through this day.
  census_date: string
  // Days in the range with census data: average daily census divides by these.
  census_range_days: number
  neutral_per_diem: number
  items: FacilityHistorical[]
}

/** Medicare PDPM stays whose start, or ARD, falls from startDate to endDate, per facility. */
export function getHistoricalMedicare(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis })
  return readJson<HistoricalMedicareReport>(`${base}/api/v1/mds/historical-medicare?${params}`, signal)
}

// PDPM residents and their daily rates over a period, summed: divide at any scope.
export type MedicarePeriodTotals = { resident_days: number; actual_rates: number; neutral_rates: number }

export type FacilityLookback = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Today and each average period, by key.
  periods: Record<string, MedicarePeriodTotals>
}

export type MedicareLookbackReport = {
  census_date: string
  // Today first, then last month, the last 6 months, the last year and all time.
  // days is the generated days in each: the average daily census divides by it.
  periods: { key: string; label: string; start: string; end: string; days: number }[]
  items: FacilityLookback[]
}

export function getMedicareLookback(signal?: AbortSignal) {
  return readJson<MedicareLookbackReport>(`${medicareBase}/lookback`, signal)
}

export type MonthTotals = { resident_days: number; actual_rates: number; neutral_rates: number }

export type FacilityMonthly = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Each month with PDPM residents, keyed by its first day; a missing month is zero.
  months: Record<string, MonthTotals>
}

export type MonthlyMedicareReport = {
  census_date: string
  // Every month of the range with census, oldest first; days is what its
  // average daily census divides by.
  months: { month: string; days: number }[]
  items: FacilityMonthly[]
}

/** Months are YYYY-MM, inclusive. */
export function getMonthlyMedicare(startMonth: string, endMonth: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_month: startMonth, end_month: endMonth })
  return readJson<MonthlyMedicareReport>(`${base}/api/v1/mds/monthly-medicare?${params}`, signal)
}

export type HistoricalDailyTrend = {
  census_date: string
  // Every day of the range through the census day.
  // Rates and days since admission are summed over the day's residents:
  // divide by census for the day's averages.
  days: { date: string; census: number; neutral_rates: number; actual_rates: number; stay_days: number }[]
}

/** PDPM census and summed neutral rate each day of the range, over the given
 * facilities, or all of them when the list is empty. */
export function getHistoricalDaily(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    facilityIds: string[], signal?: AbortSignal) {
  // The table's stays, by the same date basis, so the trend and table agree.
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis })
  facilityIds.forEach(id => params.append('facility_ids', id))
  return readJson<HistoricalDailyTrend>(`${base}/api/v1/mds/historical-medicare/daily?${params}`, signal)
}

const historicalBase = `${base}/api/v1/mds/historical-medicare`

/** One Medicare PDPM stay in the range, as Historical Medicare PDPM counts it. */
export type HistoricalResident = {
  payer_stay_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Federal Medicare or Managed Medicare PDPM.
  payer_label: string
  payer_name: string
  // First day of this Medicare payer period.
  medicare_start: string
  // The 5-day assessment's reference date; null until it is coded.
  ard: string | null
  // Yes while this Medicare stay is still running on the census day.
  active: 'Yes' | 'No'
  // Days on this Medicare stay, through its end or the census day.
  medicare_days: number
  // Four-letter PDPM code, or "Missing care code" until it is coded.
  pdpm_score: string
  // Revenue per Medicare day, at the actual and the neutral rate.
  average_rate: number
  neutral_rate: number
  total_revenue: number
  neutral_revenue: number
}

export type HistoricalResidentsPage = {
  items: HistoricalResident[]; total: number; limit: number; offset: number; census_date: string
}

function historicalResidentParameters(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    query: MedicareResidentsQuery, offset = 0) {
  return new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis,
    limit: '50', offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident', direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getHistoricalResidents(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    offset: number, query: MedicareResidentsQuery, signal?: AbortSignal) {
  return readJson<HistoricalResidentsPage>(
    `${historicalBase}/residents?${historicalResidentParameters(startDate, endDate, dateBasis, query, offset)}`, signal)
}

/** The filter-options endpoint for one date basis, so menus match the table. */
export const historicalResidentFilterOptions = (dateBasis: 'start' | 'ard') =>
  `${historicalBase}/residents/filter-options?${new URLSearchParams({ date_basis: dateBasis })}`

export async function downloadHistoricalResidents(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    query: MedicareResidentsQuery) {
  const response = await authorizedFetch(
    `${historicalBase}/residents/export?${historicalResidentParameters(startDate, endDate, dateBasis, query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `historical-medicare-pdpm-residents-${startDate}-to-${endDate}-by-${dateBasis}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Medicare PDPM stays whose start, or 5-day ARD, falls from startDate to endDate,
 * counted by PDPM category per facility. Stays not yet coded are in no_score. */
export function getHistoricalCategories(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis })
  return readJson<CategoriesReport>(`${base}/api/v1/mds/historical-medicare/categories?${params}`, signal)
}

/** A facility's PDPM residents and rates with their category counts. */
export type FacilityOverview = FacilityMedicare & { primary_diagnosis: PrimaryDiagnosis; pt_ot: PtOt; slp: Slp; nursing: Nursing; nursing_category: Record<string, number>; nta: Nta; depression: Depression; speech: Speech; no_score: number; no_score_days: number }
export type OverviewReport = { census_date: string; items: FacilityOverview[] }

const noDiagnosis: PrimaryDiagnosis = { major_joint: 0, ortho: 0, acute_neuro: 0, medical_management: 0 }
const noFunction: PtOt = { score_0_5: 0, score_6_9: 0, score_10_23: 0, score_24: 0 }
const noSpeech: Speech = { cognitive_impairment: 0, acute_neuro: 0, mechanically_altered_diet: 0, swallowing_disorder: 0,
  slp_comorbidity: 0 }

/** The Overview tab: the residents-and-rates report and the category counts,
 * fetched together and joined by facility. Both list every facility on the same
 * census day, so the join loses nothing. */
export async function getMedicareOverview(signal?: AbortSignal): Promise<OverviewReport> {
  const [medicare, categories] = await Promise.all([getCurrentMedicare(signal), getMedicareCategories(signal)])
  const counts = new Map(categories.items.map(item => [item.facility_id, item]))
  return { census_date: medicare.census_date, items: medicare.items.map(item => ({ ...item,
    primary_diagnosis: counts.get(item.facility_id)?.primary_diagnosis ?? noDiagnosis,
    pt_ot: counts.get(item.facility_id)?.pt_ot ?? noFunction,
    slp: counts.get(item.facility_id)?.slp ?? {},
    nursing: counts.get(item.facility_id)?.nursing ?? { score_0_5: 0, score_6_14: 0, score_15_16: 0 },
    nursing_category: counts.get(item.facility_id)?.nursing_category ?? {},
    nta: counts.get(item.facility_id)?.nta ?? {},
    depression: counts.get(item.facility_id)?.depression ?? { yes: 0, no: 0 },
    no_score: counts.get(item.facility_id)?.no_score ?? 0,
    no_score_days: counts.get(item.facility_id)?.no_score_days ?? 0,
    speech: counts.get(item.facility_id)?.speech ?? noSpeech })) }
}

// --- Current Medicaid ------------------------------------------------------

const medicaidBase = `${base}/api/v1/mds/current-medicaid`

/** A Texas facility's Medicaid residents on the census day: counts and sums
 * for the Overview, and the coded residents by category. Sum at any scope, then
 * divide once. */
export type FacilityMedicaid = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  residents: number
  // Every resident's daily rate, summed, and their days since admission.
  actual_rates: number
  resident_days: number
  // Residents with no case-mix code yet, and their days since admission.
  no_score: number
  no_score_days: number
  nursing: Nursing
  nursing_category: Record<string, number>
  nta: Nta
}

export type MedicaidOverviewReport = { census_date: string; items: FacilityMedicaid[] }

export function getMedicaidOverview(signal?: AbortSignal) {
  return readJson<MedicaidOverviewReport>(medicaidBase, signal)
}

export type FacilityMedicaidLookback = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Today and each average period, by key: resident-days and summed rates.
  periods: Record<string, { resident_days: number; actual_rates: number }>
}

export type MedicaidLookbackReport = {
  census_date: string
  periods: { key: string; label: string; start: string; end: string; days: number }[]
  items: FacilityMedicaidLookback[]
}

export function getMedicaidLookback(signal?: AbortSignal) {
  return readJson<MedicaidLookbackReport>(`${medicaidBase}/lookback`, signal)
}

export type MedicaidResident = {
  stay_id: string
  payer_stay_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  payer_name: string
  admission_date: string
  length_of_stay: number
  // The current code's assessment reference date; null until coded.
  ard: string | null
  // Two letters, nursing and NTA, or "Missing care code" until coded.
  case_mix_code: string
  daily_rate: number
  // Medicaid revenue on this payer through the census day.
  total_revenue: number
}

export type MedicaidResidentsPage = {
  items: MedicaidResident[]; total: number; limit: number; offset: number; census_date: string
}

export const medicaidResidentFilterOptions = `${medicaidBase}/residents/filter-options`

function medicaidResidentParameters(query: MedicareResidentsQuery, offset = 0) {
  return new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident',
    direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getMedicaidResidents(offset: number, query: MedicareResidentsQuery, signal?: AbortSignal) {
  return readJson<MedicaidResidentsPage>(`${medicaidBase}/residents?${medicaidResidentParameters(query, offset)}`, signal)
}

export async function downloadMedicaidResidents(query: MedicareResidentsQuery, censusDate: string) {
  const response = await authorizedFetch(`${medicaidBase}/residents/export?${medicaidResidentParameters(query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `current-medicaid-residents-${censusDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- Historical Medicaid ---------------------------------------------------

const medicaidHistoryBase = `${base}/api/v1/mds/historical-medicaid`

/** A Texas facility's Medicaid stays whose start, or first ARD, falls in the
 * range: summed for the page to divide at any scope. */
export type FacilityHistoricalMedicaid = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  stays: number
  // Days on those stays through their end or the census day, and their revenue.
  medicaid_days: number
  actual_revenue: number
  // Days inside the range a Texas Medicaid resident was in a bed.
  census_days: number
}

export type HistoricalMedicaidReport = {
  start_date: string
  end_date: string
  date_basis: 'start' | 'ard'
  census_date: string
  // Days of the range with census data: what average daily census divides by.
  census_range_days: number
  items: FacilityHistoricalMedicaid[]
}

function medicaidRangeParameters(startDate: string, endDate: string, dateBasis: 'start' | 'ard') {
  return new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis })
}

export function getHistoricalMedicaid(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    signal?: AbortSignal) {
  return readJson<HistoricalMedicaidReport>(
    `${medicaidHistoryBase}?${medicaidRangeParameters(startDate, endDate, dateBasis)}`, signal)
}

export type HistoricalMedicaidDaily = {
  census_date: string
  // Every day of the range through the census day; rates and days since
  // admission are summed over the day's residents: divide by census.
  days: { date: string; census: number; actual_rates: number; stay_days: number }[]
}

/** Texas Medicaid census each day of the range, over the given facilities, or
 * all of them when the list is empty. */
export function getHistoricalMedicaidDaily(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    facilityIds: string[], signal?: AbortSignal) {
  // The table's stays, by the same date basis, so the trend and table agree.
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis })
  facilityIds.forEach(id => params.append('facility_ids', id))
  return readJson<HistoricalMedicaidDaily>(`${medicaidHistoryBase}/daily?${params}`, signal)
}

export type FacilityMedicaidCategories = Pick<FacilityMedicaid,
  'facility_id' | 'facility_name' | 'state' | 'portfolio' | 'region' | 'no_score' | 'nursing' | 'nursing_category' | 'nta'>

export type MedicaidCategoriesReport = { census_date: string; items: FacilityMedicaidCategories[] }

/** The same stays counted by their first code's categories; not yet coded in no_score. */
export function getHistoricalMedicaidCategories(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    signal?: AbortSignal) {
  return readJson<MedicaidCategoriesReport>(
    `${medicaidHistoryBase}/categories?${medicaidRangeParameters(startDate, endDate, dateBasis)}`, signal)
}

/** One Texas Medicaid stay in the range, as Historical Medicaid counts it. */
export type HistoricalMedicaidResident = {
  payer_stay_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  payer_name: string
  // First day of this Medicaid payer period.
  start_date: string
  // The first assessment's reference date; null until it is coded.
  ard: string | null
  active: 'Yes' | 'No'
  medicaid_days: number
  // The first code, two letters, or "Missing care code" until it is coded.
  case_mix_code: string
  // Revenue per Medicaid day; null before the stay has a day.
  average_rate: number | null
  total_revenue: number
}

export type HistoricalMedicaidResidentsPage = {
  items: HistoricalMedicaidResident[]; total: number; limit: number; offset: number; census_date: string
}

function medicaidHistoryResidentParameters(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    query: MedicareResidentsQuery, offset = 0) {
  return new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis,
    limit: '50', offset: String(offset), filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident', direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getHistoricalMedicaidResidents(startDate: string, endDate: string, dateBasis: 'start' | 'ard',
    offset: number, query: MedicareResidentsQuery, signal?: AbortSignal) {
  return readJson<HistoricalMedicaidResidentsPage>(`${medicaidHistoryBase}/residents?${
    medicaidHistoryResidentParameters(startDate, endDate, dateBasis, query, offset)}`, signal)
}

/** The filter-options endpoint for one date basis, so menus match the table. */
export const historicalMedicaidResidentFilterOptions = (dateBasis: 'start' | 'ard') =>
  `${medicaidHistoryBase}/residents/filter-options?${new URLSearchParams({ date_basis: dateBasis })}`

export async function downloadHistoricalMedicaidResidents(startDate: string, endDate: string,
    dateBasis: 'start' | 'ard', query: MedicareResidentsQuery) {
  const response = await authorizedFetch(`${medicaidHistoryBase}/residents/export?${
    medicaidHistoryResidentParameters(startDate, endDate, dateBasis, query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `historical-medicaid-residents-${startDate}-to-${endDate}-by-${dateBasis}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- Monthly Medicaid Trending ---------------------------------------------

export type FacilityMonthlyMedicaid = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Each month with Medicaid residents, keyed by its first day.
  months: Record<string, { resident_days: number; actual_rates: number }>
}

export type MonthlyMedicaidReport = {
  census_date: string
  // Every month of the range with census, oldest first, with the days its average divides by.
  months: { month: string; days: number }[]
  items: FacilityMonthlyMedicaid[]
}

/** Months are YYYY-MM, inclusive. */
export function getMonthlyMedicaid(startMonth: string, endMonth: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_month: startMonth, end_month: endMonth })
  return readJson<MonthlyMedicaidReport>(`${base}/api/v1/mds/monthly-medicaid?${params}`, signal)
}

// --- PDPM Calculator -------------------------------------------------------

const calculatorBase = `${base}/api/v1/mds/pdpm-calculator`

/** A facility and its Original Medicare PDPM contract rate: the base a code multiplies. */
export type CalculatorFacility = {
  facility_id: string; facility_name: string; state: string; portfolio: string; region: string; base_rate: number
}

export function getCalculatorFacilities(signal?: AbortSignal) {
  return readJson<{ items: CalculatorFacility[] }>(`${calculatorBase}/facilities`, signal)
}

export type CalculatorComponent = {
  id: 'pt' | 'ot' | 'slp' | 'nursing' | 'nta' | 'non_case_mix'
  label: string
  // The code letter its CMI comes from; null for non-case-mix.
  letter: string | null
  // Its share of the facility's base rate, the CMI, and the two multiplied.
  base: number
  cmi: number | null
  adjusted: number
  // Its pay over the whole 100 days, day factors applied.
  total: number
}

export type PdpmCalculation = {
  facility: CalculatorFacility
  code: string
  components: CalculatorComponent[]
  days: { day: number; rate: number; therapy_factor: number; nta_factor: number }[]
  // Runs of days at one rate: the NTA premium, the baseline, each taper week.
  phases: { start: number; end: number; label: string; days: number; rate: number; total: number; cumulative: number }[]
  total_revenue: number
  average_rate: number
  day_one_rate: number
  last_day_rate: number
  last_therapy_factor: number
  // The NTA boost's extra over three ordinary NTA days.
  nta_premium: number
  benefit_days: number
}

/** A PDPM code priced at one facility over a full 100-day Medicare stay. */
export function getPdpmCalculation(facilityId: string, code: string, signal?: AbortSignal) {
  return readJson<PdpmCalculation>(`${calculatorBase}?${new URLSearchParams({ facility_id: facilityId, code })}`, signal)
}
