import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export type FacilityMedicare = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Residents on each Medicare payer on the census day.
  federal: number
  hmo: number
  commercial: number
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
  // Days since admission.
  length_of_stay: number
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
