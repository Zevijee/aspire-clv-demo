import { useEffect, useState } from 'react'
import { tableFilterRequestKey, type TableFilterSource } from '../utils/tableFilters'
import { authorizedFetch } from '../../features/auth/api'

export function useTableFilterOptions(source: TableFilterSource | undefined,
  column: string | null, filters: Record<string, string[]>, search: string) {
  const [retry, setRetry] = useState(0)
  const [result, setResult] = useState<{ key: string; options: string[]; error: string | null } | null>(null)
  const request = source && column ? tableFilterRequestKey(source, column, filters, search) : null
  const key = JSON.stringify([request, retry])
  useEffect(() => {
    if (!request) return
    const controller = new AbortController()
    const [id, startDate, endDate, columnId, otherFilters, searchTerm, endpoint] = JSON.parse(request)
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate,
      column: columnId, filters: JSON.stringify(otherFilters), search: searchTerm })
    const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void authorizedFetch(`${endpoint ?? `${baseUrl}/api/v1/table-filter-options/${id}`}?${params}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load filter options.')
        const data = await response.json() as { options: string[] }
        if (!controller.signal.aborted) setResult({ key, options: data.options, error: null })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResult({ key, options: [], error: error.message })
      })
    return () => controller.abort()
  }, [request, key])
  return {
    options: result?.key === key ? result.options : [],
    loading: request !== null && result?.key !== key,
    error: result?.key === key ? result.error : null,
    onRetry: () => setRetry((count) => count + 1),
  }
}
