import type { AdmissionsFilterOptions, FacilityAdmissionsMetrics } from '../api/admissions'
import type { DrilldownScope, DrilldownRow } from './admissionsDrilldown'

export type OverviewSelection = { scope: DrilldownScope; payers: string[]; sources: string[]; locations?: string[]; groupBy?: LocationLevel }
type Values = Record<string, string[]>
export const locationLevels = ['state', 'portfolio', 'region', 'facility'] as const

export function overviewFilterValues(selection: OverviewSelection): Values {
  return { location: selection.locations ?? [], payer: selection.payers, source: selection.sources }
}

export function overviewFilterSettings(selection: OverviewSelection): Values {
  return { level: [selection.groupBy ?? getLocationLevel(selection.locations ?? []) ?? 'state'],
    scope: selection.scope ? [JSON.stringify(selection.scope)] : [] }
}

export function overviewSelection(values: Values): OverviewSelection {
  const requestedLevel = values.level?.[0]
  const groupBy = locationLevels.find((level) => level === requestedLevel)
    ?? getLocationLevel(values.location ?? []) ?? 'state'
  return { scope: values.scope?.[0] ? JSON.parse(values.scope[0]) as DrilldownScope : null,
    locations: values.location ?? [], payers: values.payer ?? [], sources: values.source ?? [], groupBy }
}

export type LocationLevel = typeof locationLevels[number]

export function getLocationLevel(values: string[]): LocationLevel | undefined {
  return values.length ? locationLevels[JSON.parse(values[0]).length - 1] : undefined
}

export function getLocationOptions(locations: AdmissionsFilterOptions['locations'], level: LocationLevel, parentPath: string[] = []) {
  const depth = locationLevels.indexOf(level)
  const options = new Map<string, { value: string; label: string; context: string }>()
  for (const location of locations) {
    if (parentPath.some((part, index) => location[locationLevels[index]] !== part)) continue
    const path = locationLevels.slice(0, depth + 1).map((key) => location[key])
    const value = JSON.stringify(path)
    options.set(value, { value, label: path[depth], context: path.slice(0, depth).join(' / ') })
  }
  return [...options.values()].sort((a, b) => a.label.localeCompare(b.label) || a.context.localeCompare(b.context))
}

export function matchesLocation(location: { state: string; portfolio: string; region: string; facility: string }, values: string[]) {
  return !values.length || values.some((value) => {
    const path: string[] = JSON.parse(value)
    return path.every((part, index) => location[locationLevels[index]] === part)
  })
}

export function selectedOverviewFacilities(rows: FacilityAdmissionsMetrics[], locations: string[], scope: DrilldownScope) {
  return rows.filter((row) => matchesLocation({ ...row, facility: row.facility_name }, locations)
    && (!scope || (row.state === scope.state
      && (scope.portfolio === undefined || row.portfolio === scope.portfolio)
      && (scope.region === undefined || row.region === scope.region)
      && (scope.facility === undefined || row.facility_name === scope.facility))))
}

export function groupOverviewFacilities(facilities: FacilityAdmissionsMetrics[], level: LocationLevel, days: number): DrilldownRow[] {
  const depth = locationLevels.indexOf(level)
  const groups = new Map<string, { row: DrilldownRow; portfolios: Set<string>; regions: Set<string> }>()
  for (const facility of facilities) {
    const path = [facility.state, facility.portfolio, facility.region, facility.facility_name]
    const key = JSON.stringify(path.slice(0, depth + 1))
    let group = groups.get(key)
    if (!group) {
      const scope = { state: path[0], portfolio: depth >= 1 ? path[1] : undefined,
        region: depth >= 2 ? path[2] : undefined, facility: depth >= 3 ? path[3] : undefined }
      group = { portfolios: new Set(), regions: new Set(), row: {
        key, name: path[depth], state: path[0], portfolio: scope.portfolio ?? '', region: scope.region ?? null,
        scope, facilityNames: [], facilityCount: 0, portfolioCount: 0, regionCount: 0,
        current: 0, prior: 0, change: 0, averagePerDay: 0, readmissions: 0, referringHospitals: [], growth: null,
      } }
      groups.set(key, group)
    }
    group.portfolios.add(JSON.stringify(path.slice(0, 2)))
    group.regions.add(JSON.stringify(path.slice(0, 3)))
    const row = group.row
    row.facilityNames!.push(facility.facility_name)
    row.facilityCount += 1
    row.current += facility.total_admissions
    row.prior += facility.prior_period_admissions
    row.readmissions += facility.readmission_count
    row.referringHospitals = [...new Set([...row.referringHospitals, ...facility.referring_hospitals])]
  }
  return [...groups.values()].map(({ row, portfolios, regions }) => ({
    ...row, portfolioCount: portfolios.size, regionCount: regions.size,
    change: row.current - row.prior, averagePerDay: row.current / days,
    growth: row.prior ? (row.current - row.prior) / row.prior * 100 : null,
  }))
}
