import type { LocationLevel } from '../utils/admissionsOverviewFilters'
import type { DrilldownScope } from '../utils/admissionsDrilldown'
import { payerCode, readJson, type References } from './admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
export const netChangeBase = `${base}/api/v1/adt/net-change`

export type NetChangeSelection = {
  scope: DrilldownScope
  payers: string[]
  locations?: string[]
  groupBy?: LocationLevel
}

// Movements are additive across rows. Census is not -- it is a level, so the API
// reads opening from the first day of the range and closing from the last.
export type NetChangeMetrics = {
  opening_census: number
  closing_census: number
  admissions: number
  discharges: number
  payer_changes_in: number
  payer_changes_out: number
  net_change: number
  average_per_day: number
}
export type NetChangeLocation = NetChangeMetrics & {
  id: string; name: string; level: LocationLevel
  path: { level: LocationLevel; id: string; name: string }[]
  facility_ids: string[]
  facility_count: number
}
export type NetChangePayer = NetChangeMetrics & { payer_type: string }
export type NetChangeOverview = {
  range: { start: string; end: string; days: number }
  group_by: LocationLevel
  totals: NetChangeMetrics
  locations: NetChangeLocation[]
  by_payer: NetChangePayer[]
  daily: (NetChangeMetrics & { date: string })[]
  data_status: {
    complete: boolean; available_from: string | null
    available_through: string | null; generated_at: string | null
  }
}

export function netChangeParameters(selection: NetChangeSelection,
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
    if (!selected.length) params.set('match_none', 'true')
    selected.forEach(row => params.append('facility_ids', row.facility_id))
  }
  selection.payers.forEach(value => params.append('payer_types', payerCode(value)))
  return params
}

export function getNetChangeOverview(start: string, end: string, parameters: string, signal: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start)
  params.set('end_date', end)
  return readJson<NetChangeOverview>(`${netChangeBase}/overview?${params}`, signal)
}

export type MovementLogsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type Movement = {
  move_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  move_type: 'Admission' | 'Discharge' | 'Payer change'
  move_date: string
  description: string
  los_days: number | null
}

export function movementLogParameters(start: string, end: string,
    query: MovementLogsQuery, offset = 0) {
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'move-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getMovementLogs(start: string, end: string, offset: number,
    query: MovementLogsQuery, signal?: AbortSignal) {
  return readJson<{ items: Movement[]; total: number; limit: number; offset: number }>(
    `${netChangeBase}/logs?${movementLogParameters(start, end, query, offset)}`, signal)
}

export async function downloadMovementLogs(start: string, end: string, query: MovementLogsQuery) {
  const response = await fetch(`${netChangeBase}/logs/export?${movementLogParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Movement export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `net-change-logs-${start}-to-${end}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
