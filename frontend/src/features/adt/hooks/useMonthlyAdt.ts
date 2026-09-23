import { useEffect, useState } from 'react'
import { useAdmissionsReferences } from './useAdmissionsOverview'
import {
  getMonthlyTrend, monthlyFilter, monthlyParameters,
  type MonthlyRow, type MonthlyTab,
} from '../api/monthlyAdt'

export type MonthlyMovement = MonthlyRow

/** Monthly totals with their days nested.
 *
 * Each tab reads its own monthly table: net change from the payer census
 * rollup, admissions and discharges from the rollups that carry a referral
 * source and a destination. The census table cannot answer those, because
 * census is a level rather than a flow and does not divide by where a resident
 * came from.
 *
 * The days travel with each month because the table shows the highest and
 * lowest day inside it, which no month-grain table can answer.
 */
export function useMonthlyAdt({ startDate, endDate, payers, path, tab, filterValues }: {
  startDate: string; endDate: string; payers: string[]; path: string[]
  tab: MonthlyTab; filterValues: string[]
}) {
  const [attempt, setAttempt] = useState(0)
  const references = useAdmissionsReferences()
  const filter = monthlyFilter[tab as keyof typeof monthlyFilter]
  const parameters = references.data
    ? monthlyParameters({ references: references.data, payers, path, filter,
        values: filterValues }).toString()
    : null
  const key = JSON.stringify([startDate, endDate, parameters, tab, attempt])
  const [result, setResult] = useState<{ key: string; months?: MonthlyRow[]; error?: string } | null>(null)
  useEffect(() => {
    if (parameters === null) return
    const controller = new AbortController()
    void getMonthlyTrend(tab, startDate, endDate, parameters, controller.signal)
      .then(months => { if (!controller.signal.aborted) setResult({ key, months }) },
        (error: Error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }) })
    return () => controller.abort()
  }, [startDate, endDate, parameters, tab, key])
  const current = result?.key === key ? result : null
  return {
    months: current?.months ?? [],
    loading: references.loading || current === null,
    error: references.error ?? current?.error,
    onRetry: references.error ? references.onRetry : () => setAttempt(value => value + 1),
    startDate, endDate, hasPayers: payers.length > 0,
  }
}
