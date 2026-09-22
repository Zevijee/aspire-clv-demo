import { useEffect, useState } from 'react'
import { getDischargesOverview, type DischargesOverview } from '../api/dischargesOverview'

export function useDischargesOverview(start: string, end: string, parameters: string | null) {
  const [attempt, setAttempt] = useState(0)
  const key = JSON.stringify([start, end, parameters, attempt])
  const [result, setResult] = useState<{ key: string; data?: DischargesOverview; error?: string } | null>(null)
  useEffect(() => {
    if (parameters === null) return
    const controller = new AbortController()
    void getDischargesOverview(start, end, parameters, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ key, data })
    }, (error: Error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }) })
    return () => controller.abort()
  }, [start, end, parameters, key])
  const current = result?.key === key ? result : null
  return { data: current?.data, loading: current === null, error: current?.error,
    onRetry: () => setAttempt(value => value + 1) }
}
