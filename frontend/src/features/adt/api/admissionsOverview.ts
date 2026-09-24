import type { OverviewSelection, LocationLevel } from '../utils/admissionsOverviewFilters'
import type { Admission, AdmissionsLogsQuery } from './admissions'
import { authorizedFetch } from '../../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
export const admissionsBase = `${base}/api/v1/adt/admissions`

export const payerLabels: Record<string, string> = {
  medicare: 'Medicare', medicare_hmo: 'Medicare HMO', medicare_comm: 'Commercial Medicare',
  medicaid: 'Medicaid', private: 'Private Pay', hospice: 'Hospice', va: 'VA',
}
export function payerCode(value: string) {
  if (value === 'Medicare Advantage') return 'medicare_comm'
  return Object.keys(payerLabels).find(key => payerLabels[key] === value) ?? value
}
export function payerLabel(value: string) { return payerLabels[payerCode(value)] ?? value }

export type FacilityLocation = {
  facility_id: string; facility_name: string; beds: number
  state: string; portfolio_id: string; portfolio_name: string; region_id: string; region_name: string
}
type Payer = { payer_id: string; payer_type: string; payer_name: string; is_skilled: boolean }
export type References = { locations: FacilityLocation[]; payerTypes: string[] }
export type HospitalCount = { hospital_name: string; admissions: number }
export type SummaryMetrics = {
  admissions: number; readmissions: number; readmissions_30_day: number
  // Admissions that began pending Medicaid. Survives the retroactive payer
  // correction, so it stays countable after approval rewrites the payer period.
  medicaid_pending_admissions: number
  referring_hospitals: number; average_per_day: number
}
export type SummaryLocation = SummaryMetrics & {
  id: string; name: string; level: LocationLevel
  path: { level: LocationLevel; id: string; name: string }[]
  facility_ids: string[]; hospitals: HospitalCount[]
}
export type AdmissionsOverview = {
  range: { start: string; end: string; days: number }; group_by: LocationLevel
  totals: SummaryMetrics; locations: SummaryLocation[]; hospitals: HospitalCount[]
  by_payer: { payer_type: string; admissions: number }[]
  by_source: { source_type: string; admissions: number }[]
  daily: (SummaryMetrics & { date: string })[]
  data_status: { complete: boolean; available_from: string | null; available_through: string | null; generated_at: string | null }
}

export async function readJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  // credentials: the session cookie must ride along. Same-origin in a
  // deployment, but the dev server and the API are different ports, which
  // the browser treats as cross-origin and so omits cookies by default.
  const response = await authorizedFetch(url, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`)
  }
  return await response.json() as T
}

async function allReferenceRows<T>(name: string): Promise<T[]> {
  const rows: T[] = []
  while (true) {
    const page = await readJson<{ items: T[]; total: number }>(`${base}/api/v1/reference/${name}?limit=500&offset=${rows.length}`)
    rows.push(...page.items)
    if (rows.length >= page.total) return rows
    if (!page.items.length) throw new Error('Reference data changed while loading. Please retry.')
  }
}
let referenceCache: { expires: number; promise: Promise<References> } | null = null
export function getAdmissionsReferences(refresh = false): Promise<References> {
  if (refresh || !referenceCache || referenceCache.expires < Date.now()) {
    const promise = Promise.all([allReferenceRows<FacilityLocation>('locations'), allReferenceRows<Payer>('payers')])
      .then(([locations, payers]) => ({ locations, payerTypes: [...new Set(payers.map(row => row.payer_type))].sort() }))
    referenceCache = { expires: Date.now() + 60_000, promise }
    void promise.catch(() => { if (referenceCache?.promise === promise) referenceCache = null })
  }
  return referenceCache.promise
}

export function selectionParameters(selection: OverviewSelection, references: References, level: LocationLevel) {
  const params = new URLSearchParams({ group_by: level })
  const scope = selection.scope
  if (scope || selection.locations?.length) {
    const selected = references.locations.filter(row => {
      const path = [row.state, row.portfolio_name, row.region_name, row.facility_name]
      const customMatches = !selection.locations?.length || selection.locations.some(value => {
        const selectedPath = JSON.parse(value) as string[]
        return selectedPath.every((part, index) => part === path[index])
      })
      return customMatches && (!scope || (row.state === scope.state
        && (scope.portfolio === undefined || row.portfolio_name === scope.portfolio)
        && (scope.region === undefined || row.region_name === scope.region)
        && (scope.facility === undefined || row.facility_name === scope.facility)))
    })
    if (!selected.length) params.set('match_none', 'true')
    selected.forEach(row => params.append('facility_ids', row.facility_id))
  }
  selection.payers.forEach(value => params.append('payer_types', payerCode(value)))
  selection.sources.forEach(value => params.append('source_types', value))
  return params
}

export function getAdmissionsOverview(start: string, end: string, parameters: string, signal: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start); params.set('end_date', end)
  return readJson<AdmissionsOverview>(`${admissionsBase}/overview?${params}`, signal)
}

export function logParameters(start: string, end: string, query: AdmissionsLogsQuery, offset = 0) {
  const filters = Object.fromEntries(Object.entries(query.filters).map(([key, values]) =>
    [key, key === 'payer' ? values.map(payerLabel) : values]))
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'admission-date', direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export async function downloadAdmissionLogs(start: string, end: string, query: AdmissionsLogsQuery) {
  const response = await authorizedFetch(`${admissionsBase}/logs/export?${logParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Admission export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = `admission-logs-${start}-to-${end}.csv`
  document.body.appendChild(anchor); anchor.click(); anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function getAdmissionLogs(start: string, end: string, offset: number, query: AdmissionsLogsQuery, signal?: AbortSignal) {
  return readJson<{ items: Admission[]; total: number; limit: number; offset: number }>(`${admissionsBase}/logs?${logParameters(start, end, query, offset)}`, signal)
}
