// Filter keys are the API's log column ids, so a URL written here is a valid
// query without translation. 'facility-id' carries saved ids rather than names.
const keys = ['resident', 'facility', 'state', 'portfolio', 'region',
  'previous-payer', 'previous-payer-name', 'new-payer', 'new-payer-name',
  'category', 'status', 'facility-id'] as const

export function payerChangeLogsParams(current: URLSearchParams,
    selections: Record<string, string[]>, startDate: string, endDate: string) {
  const params = new URLSearchParams(current)
  for (const key of [...params.keys()]) if (key.startsWith('logs_')) params.delete(key)
  params.set('view', 'logs')
  params.set('start_date', startDate)
  params.set('end_date', endDate)
  for (const [key, values] of Object.entries(selections)) {
    for (const value of values) params.append(`logs_${key}`, value)
  }
  return params
}

export function getPayerChangeLogsFilters(params: URLSearchParams): Record<string, string[]> {
  return Object.fromEntries(keys.map(key => [key, params.getAll(`logs_${key}`)])
    .filter(([, values]) => values.length > 0))
}
