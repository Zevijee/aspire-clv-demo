// Filter keys are the API's log column ids, so a URL written here is a valid
// query without translation. 'facility-id' carries saved ids rather than names.
const keys = ['resident', 'facility', 'state', 'portfolio', 'region', 'payer', 'payer-name',
  'destination-type', 'destination', 'disposition', 'facility-id'] as const

export type DischargeCount = 'total' | 'ama' | 'hospitalTransfers'

export function dischargeLogsParams(current: URLSearchParams, facilityIds: string[],
    filters: { payers: string[]; destinations: string[] }, count: DischargeCount,
    startDate: string, endDate: string) {
  const params = new URLSearchParams(current)
  for (const key of [...params.keys()]) if (key.startsWith('logs_')) params.delete(key)
  params.set('view', 'logs')
  params.set('start_date', startDate)
  params.set('end_date', endDate)
  const selection: Record<string, string[]> = {
    'facility-id': facilityIds,
    payer: filters.payers,
    // A hospital transfer is the Hospital destination, so narrow the destination
    // rather than adding a disposition the row grain cannot express on its own.
    'destination-type': count === 'hospitalTransfers' ? ['Hospital'] : filters.destinations,
    disposition: count === 'ama' ? ['AMA'] : [],
  }
  for (const [key, values] of Object.entries(selection)) {
    for (const value of values) params.append(`logs_${key}`, value)
  }
  return params
}

export function getDischargeLogsFilters(params: URLSearchParams): Record<string, string[]> {
  return Object.fromEntries(keys.map(key => [key, params.getAll(`logs_${key}`)])
    .filter(([, values]) => values.length > 0))
}

export const dischargeLogKeys = keys
