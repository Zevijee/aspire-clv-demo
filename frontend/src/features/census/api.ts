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

export function getLiveCensus(signal?: AbortSignal) {
  return readJson<LiveCensusReport>(`${base}/api/v1/census/live`, signal)
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
