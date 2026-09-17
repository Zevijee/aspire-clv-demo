import type { TableQuery } from '../../../shared/components/Table'

export type Movement = {
  move_id: string
  resident_name: string
  state: string
  portfolio: string
  region: string
  facility_name: string
  move_type: 'Admission' | 'Discharge' | 'Payer change'
  move_date: string
  description: string
  los_days: number | null
}
export type MovementsPage = { items: Movement[]; total: number }

export async function getMovements(startDate: string, endDate: string, offset: number,
  query: TableQuery, exportAll = false, signal?: AbortSignal): Promise<MovementsPage> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate,
    offset: String(offset), page_size: '50', sort_by: query.sort?.columnId ?? 'move_date',
    sort_direction: query.sort?.direction ?? 'descending', filters: JSON.stringify(query.filters) })
  if (exportAll) params.set('export_all', 'true')
  if (query.search?.trim()) params.set('search', query.search.trim())
  const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${base}/api/v1/adt/net-change/logs?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Movement logs could not load (status ${response.status}).`)
  }
  return response.json() as Promise<MovementsPage>
}
