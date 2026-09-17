import { trendBlockSize, groupTrendPeriods } from '../../../shared/utils/trendPeriods'
import { useEffect, useState } from 'react'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { getDischargesDailyTrend, type DischargeChartFilters } from '../api/discharges'

export function DischargesDailyTrend({ startDate, endDate, path, filters }: {
  startDate: string; endDate: string; path: string[]; filters: DischargeChartFilters
}) {
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, path, filters, retry])
  const [response, setResponse] = useState<{
    key: string; items: { date: string; value: number }[]; error: string | null
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getDischargesDailyTrend(startDate, endDate, path, filters, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setResponse({ key, items, error: null })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResponse({ key, items: [], error: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, path, filters, key])
  const result = response?.key === key ? response : null
  const blockSize = trendBlockSize(startDate, endDate)
  const items = groupTrendPeriods(result?.items ?? [], startDate, blockSize)
  return <LineChart title={blockSize === 1 ? 'Daily Discharge Trend' : 'Discharges trend'} items={items}
    valueLabel="Discharges"
    variant="bar"
    barColor="var(--color-table-change-adverse)"
    height={400}
    subtitle={blockSize === 1 ? 'Total discharges each day' : `Total discharges per ${blockSize}-day period. The tooltip shows the exact dates and day count, including any shorter final period.`}
    loading={result === null} error={result?.error} onRetry={() => setRetry((count) => count + 1)} />
}
