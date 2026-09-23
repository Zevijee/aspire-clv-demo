import { useEffect, useState } from 'react'
import {
  getReferringHospitalPerformance, type ReferringHospitalPerformance,
} from '../api/referringHospitalPerformance'

/** Naming a hospital loads that one in detail; `skip` holds the request back. */
export function useReferringHospitalPerformance(payers: string[],
    hospital: string | null = null, skip = false) {
  const [attempt, setAttempt] = useState(0)
  const payerKey = JSON.stringify(payers)
  const key = JSON.stringify([payerKey, hospital, attempt])
  const [result, setResult] = useState<
    { key: string; data?: ReferringHospitalPerformance; error?: string } | null>(null)
  useEffect(() => {
    if (skip) return
    const controller = new AbortController()
    void getReferringHospitalPerformance(JSON.parse(payerKey) as string[], hospital,
      controller.signal).then(data => {
        if (!controller.signal.aborted) setResult({ key, data })
      }, (error: Error) => {
        if (!controller.signal.aborted) setResult({ key, error: error.message })
      })
    return () => controller.abort()
  }, [payerKey, hospital, skip, key])
  const current = result?.key === key ? result : null
  return { data: current?.data, loading: !skip && current === null, error: current?.error,
    onRetry: () => setAttempt(value => value + 1) }
}
