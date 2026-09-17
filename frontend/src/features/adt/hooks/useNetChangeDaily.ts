import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import type { DailyChangeItem } from '../../../shared/components/charts/DailyChangeChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'

export type DailyMovement = DailyChangeItem & {
  admissions: number; discharges: number; payer_changes_in: number; payer_changes_out: number
}

export function useNetChangeDaily(range?: { startDate: string; endDate: string; payers?: string[]; path?: string[] }) {
  const [params] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const [retry, setRetry] = useState(0)
  const request = new URLSearchParams({
    start_date: range?.startDate ?? params.get('start_date') ?? defaults.startDate,
    end_date: range?.endDate ?? params.get('end_date') ?? defaults.endDate,
    locations: range ? '[]' : JSON.stringify(params.getAll('net_location').map(value => JSON.parse(value))),
    path: range ? JSON.stringify(range.path ?? []) : JSON.stringify(params.getAll('net_scope').slice(0, 4)),
  })
  const payers = range ? range.payers ?? [] : params.getAll('net_payer')
  payers.forEach(payer => request.append('payer_type', payer))
  const query = request.toString()
  const key = JSON.stringify([query, retry])
  const [response, setResponse] = useState<{
    key: string; items: DailyMovement[]; error?: string
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/adt/net-change/daily?${query}`, { signal: controller.signal })
      .then(async response => {
        const body = await response.json()
        if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Daily net change could not load.')
        return body as { items: DailyMovement[] }
      }).then(data => {
        if (!controller.signal.aborted) setResponse({ key, items: data.items })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResponse({ key, items: [], error: error.message })
      })
    return () => controller.abort()
  }, [query, key])
  const result = response?.key === key ? response : null
  return { items: result?.items ?? [], loading: result === null, error: result?.error,
    onRetry: () => setRetry(value => value + 1),
    startDate: request.get('start_date')!, endDate: request.get('end_date')!,
    hasPayers: payers.length > 0 }
}
