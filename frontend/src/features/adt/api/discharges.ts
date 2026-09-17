import type { TableQuery } from '../../../shared/components/Table'

export type Discharge = {
  discharge_id: string
  resident_name: string
  facility_name: string
  state: string
  region: string
  portfolio: string
  start_date: string
  discharge_date: string
  payer_type: string
  payer_name: string
  discharge_type: string
  destination_type: string
  destination_name: string
  los_days: number
}

export type DischargesPage = {
  items: Discharge[]
  total: number
  filter_options: Record<string, string[]>
}

export async function getDischargesByDestination(startDate: string, endDate: string,
  path: string[], signal?: AbortSignal, filters: DischargeChartFilters = {}): Promise<{ label: string; value: number }[]> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const keys = ['state', 'portfolio', 'region', 'facility_name']
  path.forEach((value, index) => params.set(keys[index], value))
  appendDischargeChartFilters(params, filters)
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/v1/adt/discharges/by-destination?${params}`, { signal })
  if (!response.ok) throw new Error(`Discharge destinations request failed with status ${response.status}.`)
  return response.json() as Promise<{ label: string; value: number }[]>
}

export async function getDischargesByPayer(startDate: string, endDate: string,
  path: string[], signal?: AbortSignal, filters: DischargeChartFilters = {}): Promise<{ label: string; value: number }[]> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const keys = ['state', 'portfolio', 'region', 'facility_name']
  path.forEach((value, index) => params.set(keys[index], value))
  appendDischargeChartFilters(params, filters)
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/v1/adt/discharges/by-payer?${params}`, { signal })
  if (!response.ok) throw new Error(`Discharge payers request failed with status ${response.status}.`)
  return response.json() as Promise<{ label: string; value: number }[]>
}

export type DischargeFacilityMetrics = {
  total_los_days: number
  facility_code: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  ama_discharges: number
  hospital_transfers: number
  total_discharges: number
  prior_period_discharges: number
}

export type DischargeOverview = {
  items: DischargeFacilityMetrics[]
  days: number
  prior_start_date: string
  prior_end_date: string
}

export async function getDischargeOverview(startDate: string, endDate: string,
  signal?: AbortSignal, filters: DischargeChartFilters = {}): Promise<DischargeOverview> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  appendDischargeChartFilters(params, filters)
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/v1/adt/discharges/overview?${params}`, { signal })
  if (!response.ok) throw new Error(`Discharges overview request failed with status ${response.status}.`)
  return response.json() as Promise<DischargeOverview>
}

export async function getDischarges(startDate: string, endDate: string, offset: number,
  query: TableQuery, exportAll = false, signal?: AbortSignal): Promise<DischargesPage> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate,
    offset: String(offset), page_size: '50', sort_by: query.sort?.columnId ?? 'discharge_date',
    sort_direction: query.sort?.direction ?? 'descending' })
  if (exportAll) params.set('export_all', 'true')
  if (query.search?.trim()) params.set('search', query.search.trim())
  for (const [key, values] of Object.entries(query.filters)) {
    for (const value of values) params.append(key, value)
  }
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/v1/adt/discharges?${params}`, { signal })
  if (!response.ok) throw new Error(`Discharges request failed with status ${response.status}.`)
  return response.json() as Promise<DischargesPage>
}


export type DischargeChartFilters = { locations?: string[]; payers?: string[]; destinations?: string[] }

function appendDischargeChartFilters(params: URLSearchParams, filters: DischargeChartFilters) {
  filters.locations?.forEach((value) => params.append('location', value))
  filters.payers?.forEach((value) => params.append('payer_type', value))
  filters.destinations?.forEach((value) => params.append('destination_type', value))
}

export async function getDischargesDailyTrend(startDate: string, endDate: string,
  path: string[], filters: DischargeChartFilters, signal?: AbortSignal): Promise<{ date: string; value: number }[]> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const keys = ['state', 'portfolio', 'region', 'facility_name']
  path.forEach((value, index) => params.set(keys[index], value))
  appendDischargeChartFilters(params, filters)
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${baseUrl}/api/v1/adt/discharges/daily-trend?${params}`, { signal })
  if (!response.ok) throw new Error(`Discharge trend request failed with status ${response.status}.`)
  return response.json() as Promise<{ date: string; value: number }[]>
}
