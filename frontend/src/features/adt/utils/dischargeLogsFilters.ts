import type { DischargeChartFilters } from '../api/discharges'

const keys = ['state', 'portfolio', 'region', 'facility_name', 'payer_type', 'payer_name', 'destination_type', 'destination_name', 'discharge_type', 'resident_name'] as const
export type DischargeCount = 'total' | 'ama' | 'hospitalTransfers'

export function dischargeLogsParams(current: URLSearchParams, facilityNames: string[],
  filters: DischargeChartFilters, count: DischargeCount) {
  const params = new URLSearchParams(current)
  for (const key of keys) params.delete(`logs_${key}`)
  params.set('view', 'logs')
  const selection: Record<string, string[]> = {
    facility_name: facilityNames,
    payer_type: filters.payers ?? [],
    destination_type: count === 'hospitalTransfers' ? ['Hospital'] : filters.destinations ?? [],
    discharge_type: count === 'ama' ? ['AMA'] : count === 'hospitalTransfers' ? ['Transfer'] : [],
  }
  for (const [key, values] of Object.entries(selection)) {
    for (const value of values) params.append(`logs_${key}`, value)
  }
  return params
}

export function getDischargeLogsFilters(params: URLSearchParams): Record<string, string[]> {
  return Object.fromEntries(keys.map((key) => [key, params.getAll(`logs_${key}`)])
    .filter(([, values]) => values.length > 0))
}
