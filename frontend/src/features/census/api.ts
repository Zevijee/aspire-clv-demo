import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export type FacilityCensus = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  capacity: number
  census: number
  // Every resident, whatever payers are selected: empty beds come from this.
  all_census: number
  skilled_census: number
  // Census by payer type; types with no residents are omitted.
  payer_census: Record<string, number>
  // Every resident's daily rate summed by payer type. Sum these and the census
  // first, then divide once, so the average is weighted by residents.
  payer_daily_rates: Record<string, number>
  // Census on each lookback day by its key; null when that day was never generated.
  history: Record<string, number | null>
  // Unrounded average daily census over the trailing year, or null if incomplete.
  year_average: number | null
  // Unrounded, so summing facilities gives the parent average exactly. Null when
  // the previous month is not completely generated.
  previous_average: number | null
  previous_skilled_average: number | null
}

export type LiveCensusReport = {
  as_of: string
  census_date: string
  previous_month: string
  previous_month_days: number
  lookback: { key: string; label: string; date: string }[]
  year_start: string
  year_end: string
  items: FacilityCensus[]
  data_status: { available_from: string | null; available_through: string | null; generated_at: string | null }
}

/** Payer types narrow census and its averages; the payer mix and rates keep every payer. */
export function getLiveCensus(payers: string[], signal?: AbortSignal) {
  const params = new URLSearchParams()
  payers.forEach(payer => params.append('payer_types', payer))
  return readJson<LiveCensusReport>(`${base}/api/v1/census/live?${params}`, signal)
}

export const censusBase = `${base}/api/v1/census`

export type CensusResidentsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type CensusResident = {
  stay_id: string
  resident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  admission_date: string
  days_in_facility: number
  is_readmission: boolean
  care_level: string
  payer_type: string
  payer_name: string
  is_skilled: boolean
  payer_since: string
  // The census day's rate, after PDPM for skilled payers.
  daily_rate: number
}

export type CensusResidentsPage = {
  items: CensusResident[]; total: number; limit: number; offset: number; census_date: string
}

export function censusResidentParameters(query: CensusResidentsQuery, offset = 0) {
  return new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident',
    direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getCensusResidents(offset: number, query: CensusResidentsQuery, signal?: AbortSignal) {
  return readJson<CensusResidentsPage>(`${censusBase}/residents?${censusResidentParameters(query, offset)}`, signal)
}

export async function downloadCensusResidents(query: CensusResidentsQuery, censusDate: string) {
  const response = await authorizedFetch(`${censusBase}/residents/export?${censusResidentParameters(query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `census-residents-${censusDate}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type ResidentSummary = {
  resident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Days in a bed across every stay, through `as_of`.
  days_in_facility: number
  stays: number
  admissions: number
  discharges: number
  is_current: boolean
  // Distinct payer plans across every stay.
  payers: number
}

export type ResidentSummariesPage = {
  items: ResidentSummary[]; total: number; limit: number; offset: number; as_of: string | null
}

export function residentSummaryParameters(query: CensusResidentsQuery, offset = 0) {
  return new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident',
    direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
}

export function getResidentSummaries(offset: number, query: CensusResidentsQuery, signal?: AbortSignal) {
  return readJson<ResidentSummariesPage>(
    `${censusBase}/resident-summaries?${residentSummaryParameters(query, offset)}`, signal)
}

export async function downloadResidentSummaries(query: CensusResidentsQuery) {
  const response = await authorizedFetch(`${censusBase}/resident-summaries/export?${residentSummaryParameters(query)}`)
  if (!response.ok) throw new Error('Resident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'residents.csv'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type FacilityTrend = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  capacity: number
  // Every day's closing census, summed over the range.
  census_days: number
  opening_census: number
  closing_census: number
}

export type CensusTrendingReport = {
  range: { start: string; end: string; days: number }
  items: FacilityTrend[]
}

function trendingParameters(startDate: string, endDate: string, payers: string[]) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payers.forEach(payer => params.append('payer_types', payer))
  return params
}

export function getCensusTrending(startDate: string, endDate: string, payers: string[], signal?: AbortSignal) {
  return readJson<CensusTrendingReport>(`${censusBase}/trending?${trendingParameters(startDate, endDate, payers)}`, signal)
}

export type CensusDailyTrend = {
  range: { start: string; end: string; days: number }
  days: { date: string; census: number; opening_census: number }[]
}

/** Closing census each day, over the given facilities, or all when none are given. */
export function getCensusTrendingDaily(startDate: string, endDate: string, payers: string[],
    facilityIds: string[], signal?: AbortSignal) {
  const params = trendingParameters(startDate, endDate, payers)
  facilityIds.forEach(id => params.append('facility_ids', id))
  return readJson<CensusDailyTrend>(`${censusBase}/trending/daily?${params}`, signal)
}

export type BedOccupant = {
  resident_id: string
  first_name: string
  last_name: string
  gender: 'male' | 'female'
  admission_date: string
  // First day in this bed; later than admission only after a move.
  in_bed_since: string
  payer_type: string
  payer_name: string
  is_skilled: boolean
  care_level: string
  // Day of skilled coverage; null for other payers.
  skilled_day: number | null
  daily_rate: number
}

export type BedBoardReport = {
  as_of: string
  census_date: string
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Every licensed bed, ordered by wing, room and bed.
  beds: { wing: string; room: string; bed: string; occupant: BedOccupant | null }[]
  // In the building with no free bed; empty unless census exceeds beds.
  waiting: BedOccupant[]
}

export type BedBoardFacility = { facility_id: string; facility_name: string; state: string }

/** Without a facility, the API picks the first by name. */
export function getBedBoard(facilityId: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams()
  if (facilityId) params.set('facility_id', facilityId)
  return readJson<BedBoardReport>(`${base}/api/v1/census/bed-board?${params}`, signal)
}

export function getBedBoardFacilities(signal?: AbortSignal) {
  return readJson<BedBoardFacility[]>(`${base}/api/v1/census/bed-board/facilities`, signal)
}

export type MonthlyCensusFacility = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  capacity: number
  // Census days by YYYY-MM; months with none are omitted.
  census_days: Record<string, number>
  // Census at the start of each month and at the close of its last day in the
  // range, by YYYY-MM; zeros are omitted.
  opening_census: Record<string, number>
  closing_census: Record<string, number>
}

export type MonthlyCensusReport = {
  start: string
  // The end of the last month, or the latest generated day if sooner.
  end: string
  // `days` is how many of the month's days are in the range: all of them,
  // except in the month in progress.
  months: { month: string; days: number; month_days: number }[]
  items: MonthlyCensusFacility[]
}

export function getMonthlyCensus(startMonth: string, endMonth: string, payers: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_month: startMonth, end_month: endMonth })
  payers.forEach(payer => params.append('payer_types', payer))
  return readJson<MonthlyCensusReport>(`${censusBase}/monthly-trending?${params}`, signal)
}
