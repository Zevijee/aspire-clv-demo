import { useEffect, useState } from 'react'
import { payerCode, readJson, type References } from '../api/admissionsOverview'
import { netChangeBase } from '../api/netChangeOverview'
import { useAdmissionsReferences } from './useAdmissionsOverview'
import type { DailyMovement } from '../components/NetChangeDayOverDay'

export type MonthlyMovement = DailyMovement & {
  month: string
  end_date: string
  days: DailyMovement[]
}

/** Monthly totals with their days nested, from the monthly rollup.
 *
 * The chart is monthly, so it reads the monthly table rather than fetching every
 * day and bucketing in the browser. The days still come along because the table
 * shows the highest and lowest day inside each month.
 */
export function useMonthlyAdt({ startDate, endDate, payers, path }: {
  startDate: string; endDate: string; payers: string[]; path: string[]
}) {
  const [attempt, setAttempt] = useState(0)
  const references = useAdmissionsReferences()
  const parameters = references.data
    ? monthlyParameters(references.data, payers, path).toString() : null
  const key = JSON.stringify([startDate, endDate, parameters, attempt])
  const [result, setResult] = useState<{ key: string; months?: MonthlyMovement[]; error?: string } | null>(null)
  useEffect(() => {
    if (parameters === null) return
    const controller = new AbortController()
    const params = new URLSearchParams(parameters)
    params.set('start_date', startDate)
    params.set('end_date', endDate)
    void readJson<{ months: MonthlyMovement[] }>(`${netChangeBase}/monthly?${params}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResult({ key, months: data.months }) },
        (error: Error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }) })
    return () => controller.abort()
  }, [startDate, endDate, parameters, key])
  const current = result?.key === key ? result : null
  return {
    months: current?.months ?? [],
    loading: references.loading || current === null,
    error: references.error ?? current?.error,
    onRetry: references.error ? references.onRetry : () => setAttempt(value => value + 1),
    startDate, endDate, hasPayers: payers.length > 0,
  }
}

function monthlyParameters(references: References, payers: string[], path: string[]) {
  const params = new URLSearchParams()
  if (path.length) {
    // The drill-down carries location names; resolve them to saved facility ids.
    const selected = references.locations.filter(row =>
      [row.state, row.portfolio_name, row.region_name, row.facility_name]
        .every((part, index) => index >= path.length || part === path[index]))
    if (!selected.length) params.set('match_none', 'true')
    selected.forEach(row => params.append('facility_ids', row.facility_id))
  }
  payers.forEach(value => params.append('payer_types', payerCode(value)))
  return params
}
