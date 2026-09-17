import type {
  FacilityAdmissionsMetrics,
  PortfolioRegionAdmissionsMetrics,
  RegionAdmissionsMetrics,
} from '../api/admissions'

export type DrilldownScope = {
  state: string
  portfolio?: string
  region?: string
  facility?: string
} | null

export type DrilldownData = {
  portfolios: RegionAdmissionsMetrics[]
  regions: PortfolioRegionAdmissionsMetrics[]
  facilities: FacilityAdmissionsMetrics[]
}

export type DrilldownRow = {
  facilityNames?: string[]
  scope?: DrilldownScope
  key: string
  isTotal?: boolean
  name: string
  state: string
  portfolio: string
  region: string | null
  facilityCount: number
  portfolioCount: number
  regionCount: number
  current: number
  prior: number
  change: number
  averagePerDay: number
  readmissions: number
  referringHospitals: string[]
  growth: number | null
}

export function getDrilldownRowScope(row: DrilldownRow, scope: DrilldownScope): DrilldownScope {
  if (row.scope !== undefined) return row.scope
  return row.isTotal ? scope : {
    state: row.state,
    portfolio: row.portfolio || undefined,
    region: row.region ?? undefined,
    facility: scope?.region !== undefined ? row.name : undefined,
  }
}

function metrics(row: RegionAdmissionsMetrics) {
  return {
    current: row.total_admissions,
    prior: row.prior_period_admissions,
    change: row.admissions_change,
    averagePerDay: row.average_admissions_per_day,
    readmissions: row.readmission_count,
    referringHospitals: row.referring_hospitals,
    growth: row.prior_period_admissions > 0
      ? ((row.total_admissions - row.prior_period_admissions) / row.prior_period_admissions) * 100
      : null,
  }
}

function comparePerformance(left: DrilldownRow, right: DrilldownRow) {
  if (left.growth === null && right.growth !== null) return 1
  if (left.growth !== null && right.growth === null) return -1
  return (right.growth ?? 0) - (left.growth ?? 0)
    || left.name.localeCompare(right.name)
    || left.key.localeCompare(right.key)
}

export function getDrilldownRows(data: DrilldownData, scope: DrilldownScope): DrilldownRow[] {
  if (scope === null) {
    const states = new Map<string, DrilldownRow>()
    for (const row of data.portfolios) {
      const state = states.get(row.state) ?? {
        key: JSON.stringify(['state', row.state]), name: row.state, state: row.state,
        portfolio: '', region: null, portfolioCount: 0, facilityCount: 0, regionCount: 0,
        current: 0, prior: 0, change: 0, averagePerDay: 0, readmissions: 0, growth: null,
        referringHospitals: [],
      }
      state.portfolioCount += 1
      state.facilityCount += row.facility_count
      state.regionCount += row.region_count
      state.current += row.total_admissions
      state.prior += row.prior_period_admissions
      state.averagePerDay += row.average_admissions_per_day
      state.readmissions += row.readmission_count
      state.referringHospitals = [...new Set([...state.referringHospitals, ...row.referring_hospitals])]
      state.change = state.current - state.prior
      state.growth = state.prior > 0 ? state.change / state.prior * 100 : null
      states.set(row.state, state)
    }
    return [...states.values()].sort(comparePerformance)
  }

  if (scope.portfolio === undefined) {
    return data.portfolios.filter((row) => row.state === scope.state).map((row) => ({
      ...metrics(row),
      key: JSON.stringify(['portfolio', row.state, row.region]),
      name: row.region,
      state: row.state,
      portfolio: row.region,
      region: null,
      facilityCount: row.facility_count,
      portfolioCount: 1,
      regionCount: row.region_count,
    })).sort(comparePerformance)
  }

  if (scope.region === undefined) {
    return data.regions
      .filter((row) => row.state === scope.state && row.portfolio === scope.portfolio)
      .map((row) => ({
        ...metrics(row),
        key: JSON.stringify(['region', row.state, row.portfolio, row.region]),
        name: row.region,
        state: row.state,
        portfolio: row.portfolio,
        region: row.region,
        facilityCount: row.facility_count,
        portfolioCount: 0,
        regionCount: row.region_count,
      }))
      .sort(comparePerformance)
  }

  return data.facilities
    .filter((row) => row.state === scope.state
      && row.portfolio === scope.portfolio
      && row.region === scope.region
      && (scope.facility === undefined || row.facility_name === scope.facility))
    .map((row) => ({
      ...metrics(row),
      key: JSON.stringify(['facility', row.state, row.portfolio, row.region, row.facility_name]),
      name: row.facility_name,
      state: row.state,
      portfolio: row.portfolio,
      region: row.region,
      facilityCount: 1,
      portfolioCount: 0,
      regionCount: 0,
    }))
    .sort(comparePerformance)
}

export function getDrilldownTotal(rows: DrilldownRow[], days: number): DrilldownRow | null {
  if (rows.length <= 1) return null

  const total: DrilldownRow = {
    ...(rows.some((row) => row.facilityNames !== undefined)
      ? { facilityNames: [...new Set(rows.flatMap((row) => row.facilityNames ?? []))] } : {}),
    key: 'drilldown-total', isTotal: true, name: 'Total', state: '', portfolio: '', region: null,
    facilityCount: 0, portfolioCount: 0, regionCount: 0,
    current: 0, prior: 0, change: 0, averagePerDay: 0, readmissions: 0, growth: null,
    referringHospitals: [...new Set(rows.flatMap((row) => row.referringHospitals))],
  }
  for (const row of rows) {
    total.facilityCount += row.facilityCount
    total.portfolioCount += row.portfolioCount
    total.regionCount += row.regionCount
    total.current += row.current
    total.prior += row.prior
    total.readmissions += row.readmissions
  }
  total.change = total.current - total.prior
  total.averagePerDay = total.current / days
  total.growth = total.prior > 0 ? total.change / total.prior * 100 : null
  return total
}

export function getDrilldownSummary(rows: DrilldownRow[]) {
  const current = rows.reduce((total, row) => total + row.current, 0)
  const prior = rows.reduce((total, row) => total + row.prior, 0)
  const ranked = rows.filter((row) => row.prior > 0 && row.growth !== null).sort(comparePerformance)

  return {
    current,
    prior,
    change: current - prior,
    growing: rows.filter((row) => row.current > row.prior).length,
    best: ranked[0],
    worst: ranked[ranked.length - 1],
  }
}
