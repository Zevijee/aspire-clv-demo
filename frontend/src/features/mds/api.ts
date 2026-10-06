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

/** A facility's PDPM residents and rates with their category counts. */
export type FacilityOverview = FacilityMedicare & { primary_diagnosis: PrimaryDiagnosis; pt_ot: PtOt; slp: Slp; nursing: Nursing; nta: Nta; depression: Depression; speech: Speech; no_score: number; no_score_days: number }
export type OverviewReport = { census_date: string; items: FacilityOverview[] }

const noDiagnosis: PrimaryDiagnosis = { major_joint: 0, ortho: 0, acute_neuro: 0, medical_management: 0 }
const noFunction: PtOt = { score_0_5: 0, score_6_9: 0, score_10_23: 0, score_24: 0 }
const noSpeech: Speech = { cognitive_impairment: 0, acute_neuro: 0, mechanically_altered_diet: 0, swallowing_disorder: 0 }

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
    nta: counts.get(item.facility_id)?.nta ?? {},
    depression: counts.get(item.facility_id)?.depression ?? { yes: 0, no: 0 },
    no_score: counts.get(item.facility_id)?.no_score ?? 0,
    no_score_days: counts.get(item.facility_id)?.no_score_days ?? 0,
    speech: counts.get(item.facility_id)?.speech ?? noSpeech })) }
}
