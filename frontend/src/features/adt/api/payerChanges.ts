import type { TableQuery } from '../../../shared/components/Table'

export const payerTypes = ['Medicare', 'Commercial Medicare', 'Medicare HMO', 'Medicaid', 'Managed Medicaid', 'Private Pay', 'Hospice']
export type PayerChange = {
  change_id: string
  resident_name: string
  state: string
  portfolio: string
  region: string
  facility_name: string
  effective_date: string
  previous_payer_type: string
  previous_payer_name: string
  new_payer_type: string
  new_payer_name: string
  change_category: string
  previous_los_days: number
  new_los_days: number
  new_los_ongoing: boolean
  status: 'Ongoing' | 'Discharged'
}
export type PayerChangesPage = { items: PayerChange[]; total: number }
export type PayerChangeFacility = {
  facility_code: string; facility_name: string; state: string; portfolio: string; region: string
  total: number; residents: number; prior: number
}
export type PayerChangeOverview = {
  items: PayerChangeFacility[]; prior_start_date: string; prior_end_date: string
}

async function request<T>(path: string, params: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${base}/api/v1/adt/payer-changes${path}?${params}`, { signal })
  if (!response.ok) throw new Error(`Payer changes could not load (status ${response.status}).`)
  return response.json() as Promise<T>
}

export function getPayerChanges(startDate: string, endDate: string, offset: number,
  query: TableQuery, exportAll = false, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate,
    offset: String(offset), page_size: '50', sort_by: query.sort?.columnId ?? 'effective_date',
    sort_direction: query.sort?.direction ?? 'descending' })
  if (exportAll) params.set('export_all', 'true')
  if (query.search?.trim()) params.set('search', query.search.trim())
  for (const [key, values] of Object.entries(query.filters)) {
    for (const value of values) params.append(key, value)
  }
  return request<PayerChangesPage>('', params, signal)
}

export function getPayerChangeOverview(startDate: string, endDate: string, signal?: AbortSignal) {
  return request<PayerChangeOverview>('/overview',
    new URLSearchParams({ start_date: startDate, end_date: endDate }), signal)
}

export function getPayerTransitions(startDate: string, endDate: string, path: string[],
  previousPayer: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate,
    previous_payer_type: previousPayer })
  const keys = ['state', 'portfolio', 'region', 'facility_name']
  path.forEach((value, index) => params.set(keys[index], value))
  return request<{ label: string; value: number }[]>('/transitions', params, signal)
}
