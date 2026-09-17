import type { NetChangeFacility } from '../api/netChange'

export type NetChangeRow = Omit<NetChangeFacility, 'facility_code' | 'facility_name' | 'state' | 'portfolio' | 'region'> & {
  facilityCount: number; key: string; name: string; path: string[]; isTotal?: boolean
}

function sumNullable(a: number | null, b: number | null): number | null {
  return a === null || b === null ? null : a + b
}

function add(target: NetChangeRow, source: Pick<NetChangeFacility,
  'opening_census' | 'closing_census' | 'admissions' | 'discharges' | 'net_change' | 'prior_net_change' | 'payer_changes_in' | 'payer_changes_out' | 'payer_changes'> & { facilityCount?: number }) {
  target.facilityCount += source.facilityCount ?? 1
  target.opening_census = sumNullable(target.opening_census, source.opening_census)
  target.closing_census = sumNullable(target.closing_census, source.closing_census)
  target.admissions += source.admissions
  target.discharges += source.discharges
  target.net_change += source.net_change
  target.payer_changes = (target.payer_changes ?? 0) + (source.payer_changes ?? 0)
  target.payer_changes_in = (target.payer_changes_in ?? 0) + (source.payer_changes_in ?? 0)
  target.payer_changes_out = (target.payer_changes_out ?? 0) + (source.payer_changes_out ?? 0)
  target.prior_net_change = sumNullable(target.prior_net_change, source.prior_net_change)
}

function emptyRow(key: string, name: string, path: string[]): NetChangeRow {
  return { key, name, path, facilityCount: 0, opening_census: 0, closing_census: 0,
    admissions: 0, discharges: 0, net_change: 0, prior_net_change: 0 }
}

export function getNetChangeRows(facilities: NetChangeFacility[], path: string[], depth = path.length): NetChangeRow[] {
  const groups = new Map<string, NetChangeRow>()
  for (const facility of facilities) {
    const hierarchy = [facility.state, facility.portfolio, facility.region, facility.facility_name]
    if (!path.every((part, index) => hierarchy[index] === part)) continue
    const rowPath = hierarchy.slice(0, Math.min(depth + 1, 4))
    const key = JSON.stringify(rowPath)
    const row = groups.get(key) ?? emptyRow(key, rowPath.at(-1)!, rowPath)
    add(row, facility)
    groups.set(key, row)
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function getNetChangeTotal(rows: NetChangeRow[]): NetChangeRow | null {
  if (rows.length <= 1) return null
  const total = { ...emptyRow('total', 'Total', []), isTotal: true }
  rows.forEach((row) => add(total, row))
  return total
}
