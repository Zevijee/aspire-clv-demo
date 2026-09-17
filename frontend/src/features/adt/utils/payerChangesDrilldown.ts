import type { PayerChangeFacility } from '../api/payerChanges'

export type PayerChangeRow = {
  key: string; name: string; path: string[]; facilityNames: string[]
  total: number; residents: number; prior: number; change: number; isTotal?: boolean
}

export function getPayerChangeRows(facilities: PayerChangeFacility[], path: string[]): PayerChangeRow[] {
  const groups = new Map<string, PayerChangeRow>()
  for (const facility of facilities) {
    const hierarchy = [facility.state, facility.portfolio, facility.region, facility.facility_name]
    if (!path.every((part, index) => hierarchy[index] === part)) continue
    const rowPath = hierarchy.slice(0, Math.min(path.length + 1, 4))
    const key = JSON.stringify(rowPath)
    const row = groups.get(key) ?? { key, name: rowPath.at(-1)!, path: rowPath,
      facilityNames: [], total: 0, residents: 0, prior: 0, change: 0 }
    row.total += facility.total
    row.residents += facility.residents
    row.prior += facility.prior
    row.change = row.total - row.prior
    row.facilityNames.push(facility.facility_name)
    groups.set(key, row)
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function getPayerChangeTotal(rows: PayerChangeRow[]): PayerChangeRow | null {
  if (rows.length <= 1) return null
  return { key: 'total', name: 'Total', path: [], isTotal: true,
    facilityNames: rows.flatMap((row) => row.facilityNames),
    total: rows.reduce((sum, row) => sum + row.total, 0),
    residents: rows.reduce((sum, row) => sum + row.residents, 0),
    prior: rows.reduce((sum, row) => sum + row.prior, 0),
    change: rows.reduce((sum, row) => sum + row.change, 0) }
}

const keys = ['facility_name', 'state', 'portfolio', 'region', 'previous_payer_type',
  'new_payer_type', 'change_category']

export function payerChangeLogsParams(current: URLSearchParams, selections: Record<string, string[]>) {
  const params = new URLSearchParams(current)
  for (const key of [...params.keys()]) if (key.startsWith('logs_')) params.delete(key)
  params.set('view', 'logs')
  const filters = { change_category: ['Payer type'], ...selections }
  for (const [key, values] of Object.entries(filters)) {
    for (const value of values) params.append(`logs_${key}`, value)
  }
  return params
}

export function getPayerChangeLogsFilters(params: URLSearchParams): Record<string, string[]> {
  return Object.fromEntries(keys.map((key) => [key, params.getAll(`logs_${key}`)])
    .filter(([, values]) => values.length > 0))
}
