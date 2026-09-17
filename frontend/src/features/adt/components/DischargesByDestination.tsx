import { useEffect, useState } from 'react'
import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { getDischargesByDestination } from '../api/discharges'

export function DischargesByDestination({ startDate, endDate, path, selected, onChange, payers, locations }: {
  locations?: string[]
  startDate: string; endDate: string; path: string[]
  selected: string[]; onChange: (values: string[]) => void; payers: string[]
}) {
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, path, payers, locations, retry])
  const [response, setResponse] = useState<{
    key: string; items: { label: string; value: number }[]; error: string | null
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getDischargesByDestination(startDate, endDate, path, controller.signal, { payers: payers, locations })
      .then((items) => {
        if (!controller.signal.aborted) setResponse({ key, items, error: null })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResponse({ key, items: [], error: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, path, payers, locations, key])
  const result = response?.key === key ? response : null
  return <BarChartRanking title="Discharges by Destination Type"
    subtitle={`${path.length ? path.join(' / ') : 'All states'} · Ranked by discharge count`}
    clearLabel="Clear destination filter" categoryLabel="Destination type" valueLabel="Discharges"
    selectedLabels={selected} onClear={() => onChange([])}
    onSelect={(label) => onChange(selected.includes(label)
      ? selected.filter((value) => value !== label) : [...selected, label])}
    items={result?.items ?? []} loading={result === null} error={result?.error}
    onRetry={() => setRetry((count) => count + 1)} />
}
