import type { DischargeFacilityMetrics } from '../api/discharges'

export type DischargeDrilldownRow = {
  key: string
  name: string
  path: string[]
  facilityNames: string[]
  facilityCount: number
  ama: number
  hospitalTransfers: number
  total: number
  totalLosDays: number
  prior: number
  change: number
  averagePerDay: number
  averagePerFacility: number
  averagePerFacilityPerDay: number
  isTotal?: boolean
}

function metrics(total: number, prior: number, facilityCount: number, days: number) {
  return { total, prior, facilityCount, change: total - prior,
    averagePerDay: total / days,
    averagePerFacility: facilityCount ? total / facilityCount : 0,
    averagePerFacilityPerDay: facilityCount ? total / facilityCount / days : 0 }
}

export function getDischargeDrilldownRows(facilities: DischargeFacilityMetrics[],
  path: string[], days: number, depth = path.length): DischargeDrilldownRow[] {
  const groups = new Map<string, DischargeDrilldownRow>()
  for (const facility of facilities) {
    const hierarchy = [facility.state, facility.portfolio, facility.region, facility.facility_name]
    if (!path.every((part, index) => hierarchy[index] === part)) continue
    const rowPath = hierarchy.slice(0, Math.min(depth + 1, 4))
    const key = JSON.stringify(rowPath)
    const row = groups.get(key) ?? {
      key, name: rowPath[rowPath.length - 1], path: rowPath, facilityNames: [], ama: 0, hospitalTransfers: 0, totalLosDays: 0,
      ...metrics(0, 0, 0, days),
    }
    Object.assign(row, metrics(row.total + facility.total_discharges,
      row.prior + facility.prior_period_discharges, row.facilityCount + 1, days))
    row.totalLosDays += facility.total_los_days
    row.ama += facility.ama_discharges
    row.facilityNames.push(facility.facility_name)
    row.hospitalTransfers += facility.hospital_transfers
    groups.set(key, row)
  }
  return [...groups.values()].sort((left, right) => left.name.localeCompare(right.name))
}

export function getDischargeTotal(rows: DischargeDrilldownRow[], days: number): DischargeDrilldownRow | null {
  if (rows.length <= 1) return null
  return { totalLosDays: rows.reduce((sum, row) => sum + row.totalLosDays, 0), key: 'total', name: 'Total', path: [], isTotal: true,
    facilityNames: rows.flatMap((row) => row.facilityNames),
    ama: rows.reduce((sum, row) => sum + row.ama, 0),
    hospitalTransfers: rows.reduce((sum, row) => sum + row.hospitalTransfers, 0),
    ...metrics(rows.reduce((sum, row) => sum + row.total, 0),
      rows.reduce((sum, row) => sum + row.prior, 0),
      rows.reduce((sum, row) => sum + row.facilityCount, 0), days) }
}
