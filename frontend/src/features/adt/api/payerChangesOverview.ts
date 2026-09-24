import type { LocationLevel } from '../utils/admissionsOverviewFilters'
import type { DrilldownScope } from '../utils/admissionsDrilldown'
import { payerCode, readJson, type References } from './admissionsOverview'
import { authorizedFetch } from '../../auth/api'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
export const payerChangesBase = `${base}/api/v1/adt/payer-changes`

// The donuts render one card per payer type, in this order.
export const payerTypes = ['medicare', 'medicare_comm', 'medicare_hmo', 'medicaid',
  'private', 'hospice', 'va'] as const

export type PayerChangeMetrics = { changes: number; average_per_day: number }
export type PayerChangeLocation = PayerChangeMetrics & {
  id: string; name: string; level: LocationLevel
  path: { level: LocationLevel; id: string; name: string }[]
  facility_ids: string[]
  // Exact distinct residents in this scope. Not additive: a resident who changed
  // payer in two facilities appears in both, so never sum this column.
  residents: number
}
export type PayerTransition = {
  previous_payer_type: string; new_payer_type: string; changes: number
}
export type PayerChangesOverview = {
  range: { start: string; end: string; days: number }
  group_by: LocationLevel
  totals: PayerChangeMetrics
  residents: number
  locations: PayerChangeLocation[]
  transitions: PayerTransition[]
  daily: (PayerChangeMetrics & { date: string })[]
  data_status: {
    complete: boolean; available_from: string | null
    available_through: string | null; generated_at: string | null
  }
}

export type PayerChangeSelection = {
  scope: DrilldownScope
  locations?: string[]
  groupBy?: LocationLevel
  typeChangesOnly: boolean
}

export function payerChangeParameters(selection: PayerChangeSelection,
    references: References, level: LocationLevel) {
  const params = new URLSearchParams({ group_by: level })
  params.set('type_changes_only', String(selection.typeChangesOnly))
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
  return params
}

export function getPayerChangesOverview(start: string, end: string, parameters: string, signal: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start)
  params.set('end_date', end)
  return readJson<PayerChangesOverview>(`${payerChangesBase}/overview?${params}`, signal)
}

export type PayerChangeLogsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type PayerChange = {
  change_id: string
  resident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  effective_date: string
  previous_payer_type: string
  previous_payer_name: string
  new_payer_type: string
  new_payer_name: string
  change_category: string
  status: 'Ongoing' | 'Discharged'
  previous_los_days: number
  new_los_days: number
  new_los_ongoing: boolean
}

export function payerChangeLogParameters(start: string, end: string,
    query: PayerChangeLogsQuery, offset = 0) {
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'effective-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getPayerChangeLogs(start: string, end: string, offset: number,
    query: PayerChangeLogsQuery, signal?: AbortSignal) {
  return readJson<{ items: PayerChange[]; total: number; limit: number; offset: number }>(
    `${payerChangesBase}/logs?${payerChangeLogParameters(start, end, query, offset)}`, signal)
}

export async function downloadPayerChangeLogs(start: string, end: string, query: PayerChangeLogsQuery) {
  const response = await authorizedFetch(`${payerChangesBase}/logs/export?${payerChangeLogParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Payer change export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `payer-change-logs-${start}-to-${end}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export { payerCode }
