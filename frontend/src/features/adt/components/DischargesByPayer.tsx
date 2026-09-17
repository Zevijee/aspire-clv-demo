import { useEffect, useState } from 'react'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { getDischargesByPayer } from '../api/discharges'

export function DischargesByPayer({ startDate, endDate, path, selected, onChange, destinations, locations }: {
  locations?: string[]
  startDate: string; endDate: string; path: string[]
  selected: string[]; onChange: (values: string[]) => void; destinations: string[]
}) {
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, path, destinations, locations, retry])
  const [response, setResponse] = useState<{
    key: string; items: { label: string; value: number }[]; error: string | null
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getDischargesByPayer(startDate, endDate, path, controller.signal, { destinations: destinations, locations })
      .then((items) => {
        if (!controller.signal.aborted) setResponse({ key, items, error: null })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResponse({ key, items: [], error: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, path, destinations, locations, key])
  const result = response?.key === key ? response : null
  return <DonutChart title="Discharges by Payer Type"
    subtitle={`${path.length ? path.join(' / ') : 'All states'} · Discharges by payer type`}
    selectedLabels={selected} onClear={() => onChange([])}
    onSelect={(label) => onChange(selected.includes(label)
      ? selected.filter((value) => value !== label) : [...selected, label])}
    items={result?.items ?? []} loading={result === null} error={result?.error}
    onRetry={() => setRetry((count) => count + 1)} />
}
