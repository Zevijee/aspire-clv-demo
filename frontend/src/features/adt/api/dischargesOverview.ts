import type { LocationLevel } from '../utils/admissionsOverviewFilters'
import type { DrilldownScope } from '../utils/admissionsDrilldown'
import { payerCode, readJson, type References } from './admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
export const dischargesBase = `${base}/api/v1/adt/discharges`

export type DischargeSelection = {
  scope: DrilldownScope
  payers: string[]
  destinations: string[]
  locations?: string[]
  groupBy?: LocationLevel
}

// Every field is a sum except the two averages, which the API derives once from
// those sums. Never average these across rows -- add them and divide again.
export type DischargeMetrics = {
  discharges: number
  hospital_transfers: number
  ama_discharges: number
  deceased_discharges: number
  length_of_stay_days: number
  average_length_of_stay: number
  average_per_day: number
}
export type DischargeLocation = DischargeMetrics & {
  id: string; name: string; level: LocationLevel
  path: { level: LocationLevel; id: string; name: string }[]
  facility_ids: string[]
}
export type DischargesOverview = {
  range: { start: string; end: string; days: number }
  group_by: LocationLevel
  totals: DischargeMetrics
  locations: DischargeLocation[]
  by_payer: { payer_type: string; discharges: number }[]
  by_destination: { destination_type: string; discharges: number }[]
  by_disposition: { discharge_type: string; discharges: number }[]
  daily: (DischargeMetrics & { date: string })[]
  data_status: {
    complete: boolean; available_from: string | null
    available_through: string | null; generated_at: string | null
  }
}

export function dischargeSelectionParameters(selection: DischargeSelection,
    references: References, level: LocationLevel) {
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
    // An empty result must return nothing rather than everything.
    if (!selected.length) params.set('match_none', 'true')
    selected.forEach(row => params.append('facility_ids', row.facility_id))
  }
  selection.payers.forEach(value => params.append('payer_types', payerCode(value)))
  selection.destinations.forEach(value => params.append('destination_types', value))
  return params
}

export function getDischargesOverview(start: string, end: string, parameters: string, signal: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start)
  params.set('end_date', end)
  return readJson<DischargesOverview>(`${dischargesBase}/overview?${params}`, signal)
}

export type DischargeLogsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type Discharge = {
  discharge_id: string
  resident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  admission_date: string
  discharge_date: string
  payer_type: string
  payer_name: string
  destination_type: string
  destination_name: string
  discharge_type: string
  is_deceased: boolean
  is_ama: boolean
  length_of_stay: number
}

export function dischargeLogParameters(start: string, end: string, query: DischargeLogsQuery, offset = 0) {
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'discharge-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getDischargeLogs(start: string, end: string, offset: number,
    query: DischargeLogsQuery, signal?: AbortSignal) {
  return readJson<{ items: Discharge[]; total: number; limit: number; offset: number }>(
    `${dischargesBase}/logs?${dischargeLogParameters(start, end, query, offset)}`, signal)
}

export async function downloadDischargeLogs(start: string, end: string, query: DischargeLogsQuery) {
  const response = await fetch(`${dischargesBase}/logs/export?${dischargeLogParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Discharge export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `discharge-logs-${start}-to-${end}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
