export type Admission = {
  state: string
  region: string
  portfolio: string
  is_readmission: boolean
  started_medicaid_pending: boolean
  admission_date: string
  admission_id: string
  admission_source_name: string
  admission_source_type: string
  facility_name: string
  payer_name: string
  payer_type: string
  resident_name: string
}

export type AdmissionsPage = {
  filter_options: {
    state: string[]
    region: string[]
    portfolio: string[]
    admission_source: string[]
    facility: string[]
    payer: string[]
    payer_name: string[]
    source_type: string[]
  }
  items: Admission[]
  total: number
}

export type AdmissionsLogsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type RegionAdmissionsRanking = {
  admission_count: number
  region: string
}

export type RegionAdmissionsMetrics = {
  readmission_within_30_days_count?: number
  referring_hospitals: string[]
  admissions_change: number
  average_admissions_per_day: number
  facility_count: number
  medicare_admission_count: number
  medicare_admissions_change: number
  prior_period_admissions: number
  prior_period_medicare_admission_count: number
  readmission_count: number
  region: string
  region_count: number
  state: string
  total_admissions: number
}

export type FacilityAdmissionsMetrics = RegionAdmissionsMetrics & {
  facility_name: string
  portfolio: string
}

export type PortfolioRegionAdmissionsMetrics = RegionAdmissionsMetrics & {
  portfolio: string
}

export type RegionPayerAdmissionsRow = {
  admission_counts: Record<string, number>
  region: string
}

export type RegionPayerAdmissionsTable = {
  payer_types: string[]
  regions: RegionPayerAdmissionsRow[]
}

export type PayerAdmissionsDistribution = {
  admission_count: number
  payer_type: string
}

export type AdmissionSourceTypeDistribution = {
  admission_count: number
  admission_source_type: string
}

export type AdmissionsKpiMetrics = {
  average_admissions_per_day: number
  readmission_count: number
  readmission_within_30_days_count: number
  total_admissions: number
  unique_admission_source_count: number
}

export type AdmissionsKpiSummary = AdmissionsKpiMetrics & {
  days_in_range: number
  prior_period: AdmissionsKpiMetrics
}

export type AdmissionsMetricFilters = {
  sourceTypes?: string[]
  facilities: string[]
  payerTypes: string[]
  portfolios: string[]
  regions: string[]
}

export type AdmissionsFilterOptions = {
  locations: { state: string; portfolio: string; region: string; facility: string }[]
  facilities: string[]
  portfolios: string[]
  regions: string[]
}

export type AdmissionsDailyTrendItem = {
  admission_count: number
  admission_date: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export function formatPayerType(payerType: string) {
  return payerType === 'Medicare Advantage' ? 'Commercial Medicare' : payerType
}

function getAdmissionsSearchParams(startDate: string, endDate: string) {
  const searchParams = new URLSearchParams({
    end_date: endDate,
    start_date: startDate,
  })

  return searchParams
}

function appendMetricFilters(searchParams: URLSearchParams, filters: AdmissionsMetricFilters) {
  for (const [parameterName, values] of [
    ['source_type', filters.sourceTypes ?? []],
    ['payer_type', filters.payerTypes],
    ['portfolio', filters.portfolios],
    ['region', filters.regions],
    ['facility', filters.facilities],
  ] as const) {
    for (const value of values) {
      searchParams.append(parameterName, value)
    }
  }
}

export async function getRecentAdmissions(
  startDate: string,
  endDate: string,
  offset: number,
  query: AdmissionsLogsQuery,
  exportAll = false,
): Promise<AdmissionsPage> {
  const searchParams = getAdmissionsSearchParams(startDate, endDate)
  if (exportAll) searchParams.set('export_all', 'true')
  searchParams.set('offset', offset.toString())
  searchParams.set('page_size', '50')
  const readmissionValues = query.filters.readmission ?? []
  if (readmissionValues.length === 1) {
    if (readmissionValues[0] === 'Yes') searchParams.set('is_readmission', 'true')
    if (readmissionValues[0] === 'No') searchParams.set('is_readmission', 'false')
  }
  if (query.search?.trim()) {
    searchParams.set('search', query.search.trim())
  }
  if (query.sort !== null) {
    searchParams.set('sort_by', query.sort.columnId)
    searchParams.set('sort_direction', query.sort.direction)
  }

  for (const [columnId, values] of Object.entries(query.filters)) {
    const parameterName =
      columnId === 'facility'
        ? 'facility'
        : columnId === 'payer'
          ? 'payer_type'
          : columnId === 'admission-source'
            ? 'admission_source'
            : columnId === 'payer-name'
              ? 'payer_name'
              : columnId === 'source-type'
                ? 'source_type'
                : ['state', 'portfolio', 'region'].includes(columnId) ? columnId : undefined

    if (parameterName !== undefined) {
      for (const value of values) {
        searchParams.append(
          parameterName,
          parameterName === 'payer_type' && value === 'Commercial Medicare'
            ? 'Medicare Advantage'
            : value,
        )
      }
    }
  }
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions?${searchParams}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions request failed with status ${response.status}.`)
  }

  return (await response.json()) as AdmissionsPage
}

export async function getAdmissionsKpis(
  startDate: string,
  endDate: string,
  filters: AdmissionsMetricFilters,
): Promise<AdmissionsKpiSummary> {
  const searchParams = getAdmissionsSearchParams(startDate, endDate)
  appendMetricFilters(searchParams, filters)
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/kpis?${searchParams}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions KPI request failed with status ${response.status}.`)
  }

  return (await response.json()) as AdmissionsKpiSummary
}

export async function getAdmissionsByRegion(
  startDate: string,
  endDate: string,
): Promise<RegionAdmissionsRanking[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/by-region?${getAdmissionsSearchParams(startDate, endDate)}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions-by-region request failed with status ${response.status}.`)
  }

  return (await response.json()) as RegionAdmissionsRanking[]
}

export async function getAdmissionsByRegionMetrics(
  startDate: string,
  endDate: string,
  level: 'portfolio' | 'region' = 'portfolio',
  payerTypes: string[] = [],
  sourceTypes: string[] = [],
): Promise<RegionAdmissionsMetrics[]> {
  const searchParams = getAdmissionsSearchParams(startDate, endDate)
  searchParams.set('level', level)
  for (const source of sourceTypes) searchParams.append('source_type', source)
  for (const payerType of payerTypes) {
    searchParams.append('payer_type', payerType)
  }
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/by-region/metrics?${searchParams}`,
  )

  if (!response.ok) {
    throw new Error(`Regional admissions metrics request failed with status ${response.status}.`)
  }

  return (await response.json()) as RegionAdmissionsMetrics[]
}

export async function getAdmissionsByRegionLevelMetrics(
  startDate: string,
  endDate: string,
  payerTypes: string[] = [],
  sourceTypes: string[] = [],
): Promise<PortfolioRegionAdmissionsMetrics[]> {
  return (await getAdmissionsByRegionMetrics(
    startDate,
    endDate,
    'region',
    payerTypes,
    sourceTypes,
  )) as PortfolioRegionAdmissionsMetrics[]
}

export async function getAdmissionsByFacilityMetrics(
  startDate: string,
  endDate: string,
  payerTypes: string[] = [],
  sourceTypes: string[] = [],
): Promise<FacilityAdmissionsMetrics[]> {
  const params = getAdmissionsSearchParams(startDate, endDate)
  for (const source of sourceTypes) params.append('source_type', source)
  for (const payer of payerTypes) params.append('payer_type', payer)
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/by-facility/metrics?${params}`)

  if (!response.ok) {
    throw new Error(`Facility admissions metrics request failed with status ${response.status}.`)
  }

  return (await response.json()) as FacilityAdmissionsMetrics[]
}

export async function getAdmissionsByRegionAndPayer(
  startDate: string,
  endDate: string,
): Promise<RegionPayerAdmissionsTable> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/by-region-and-payer?${getAdmissionsSearchParams(startDate, endDate)}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions-by-region-and-payer request failed with status ${response.status}.`)
  }

  return (await response.json()) as RegionPayerAdmissionsTable
}

export async function getAdmissionsByPayer(
  startDate: string,
  endDate: string,
): Promise<PayerAdmissionsDistribution[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/by-payer?${getAdmissionsSearchParams(startDate, endDate)}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions-by-payer request failed with status ${response.status}.`)
  }

  return (await response.json()) as PayerAdmissionsDistribution[]
}

export async function getAdmissionsBySourceType(
  startDate: string,
  endDate: string,
  filters: AdmissionsMetricFilters,
): Promise<AdmissionSourceTypeDistribution[]> {
  const searchParams = getAdmissionsSearchParams(startDate, endDate)
  appendMetricFilters(searchParams, filters)
  const response = await fetch(
    `${apiBaseUrl}/api/v1/adt/admissions/by-admission-source-type?${searchParams}`,
  )

  if (!response.ok) {
    throw new Error(`Admissions-by-source-type request failed with status ${response.status}.`)
  }

  return (await response.json()) as AdmissionSourceTypeDistribution[]
}

export async function getAdmissionsFilterOptions(): Promise<AdmissionsFilterOptions> {
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/filter-options`)

  if (!response.ok) {
    throw new Error(`Admissions filter options request failed with status ${response.status}.`)
  }

  return (await response.json()) as AdmissionsFilterOptions
}

export async function getAdmissionsDailyTrend(
  startDate: string,
  endDate: string,
  filters: AdmissionsMetricFilters,
): Promise<AdmissionsDailyTrendItem[]> {
  const searchParams = getAdmissionsSearchParams(startDate, endDate)
  appendMetricFilters(searchParams, filters)
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/daily-trend?${searchParams}`)

  if (!response.ok) {
    throw new Error(`Daily admissions trend request failed with status ${response.status}.`)
  }

  return (await response.json()) as AdmissionsDailyTrendItem[]
}

export type HistoricalComparisons = {
  periods: { key: string; start: string; end: string }[]
  items: { name: string; state: string; portfolio: string; region: string; [key: string]: string | number | null }[]
}

export async function getHistoricalComparisons(startDate: string, endDate: string): Promise<HistoricalComparisons> {
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/historical-comparisons?${getAdmissionsSearchParams(startDate, endDate)}`)
  if (!response.ok) throw new Error('Historical comparisons could not load. Please try again.')
  return response.json() as Promise<HistoricalComparisons>
}

export type ReferringHospital = {
  historical_average_per_day: number
  expected_admissions: number
  variance_from_expected: number
  history_start_date: string
  history_end_date: string
  hospital: string
  receiving_facility_codes: string[]
  admission_count: number
  prior_period_admissions: number
  admissions_change: number
  average_admissions_per_day: number
  readmission_count: number
  readmission_within_30_days_count: number
}

export async function getReferringHospitals(startDate: string, endDate: string, filters: AdmissionsMetricFilters & { states?: string[] }): Promise<ReferringHospital[]> {
  const params = getAdmissionsSearchParams(startDate, endDate)
  appendMetricFilters(params, filters)
  for (const state of filters.states ?? []) params.append('state', state)
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/by-referring-hospital?${params}`)
  if (!response.ok) throw new Error('Referring hospitals could not load. Please try again.')
  return response.json() as Promise<ReferringHospital[]>
}

export type PayerFacilityCount = {
  facility_code: string; facility: string; state: string; portfolio: string; region: string
  payer_type: string; admissions: number
}

export async function getPayerFacilityCounts(startDate: string, endDate: string, sourceTypes: string[] = []): Promise<PayerFacilityCount[]> {
  const params = getAdmissionsSearchParams(startDate, endDate)
  for (const source of sourceTypes) params.append('source_type', source)
  const response = await fetch(`${apiBaseUrl}/api/v1/adt/admissions/payer-by-facility?${params}`)
  if (!response.ok) throw new Error('Payer admissions could not load. Please try again.')
  return response.json() as Promise<PayerFacilityCount[]>
}
