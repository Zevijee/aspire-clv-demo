import { useEffect, useState } from 'react'
import { getAdmissionsOverview, getAdmissionsReferences, type AdmissionsOverview, type References } from '../api/admissionsOverview'

export function useAdmissionsReferences() {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ attempt: number; data?: References; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getAdmissionsReferences(attempt > 0).then(data => {
      if (active) setResult({ attempt, data })
    }, (error: Error) => { if (active) setResult({ attempt, error: error.message }) })
    return () => { active = false }
  }, [attempt])
  const current = result?.attempt === attempt ? result : null
  return { data: current?.data, loading: current === null, error: current?.error,
    onRetry: () => setAttempt(value => value + 1) }
}

export function useAdmissionsOverview(start: string, end: string, parameters: string | null) {
  const [attempt, setAttempt] = useState(0)
  const key = JSON.stringify([start, end, parameters, attempt])
  const [result, setResult] = useState<{ key: string; data?: AdmissionsOverview; error?: string } | null>(null)
  useEffect(() => {
    if (parameters === null) return
    const controller = new AbortController()
    void getAdmissionsOverview(start, end, parameters, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ key, data })
    }, (error: Error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }) })
    return () => controller.abort()
  }, [start, end, parameters, key])
  const current = result?.key === key ? result : null
  return { data: current?.data, loading: current === null, error: current?.error,
    onRetry: () => setAttempt(value => value + 1) }
}
