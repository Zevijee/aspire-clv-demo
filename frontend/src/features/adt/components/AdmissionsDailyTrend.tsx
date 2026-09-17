import { trendBlockSize, groupTrendPeriods } from '../../../shared/utils/trendPeriods'
import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { LineChart } from '../../../shared/components/charts/LineChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsDailyTrend,
  type AdmissionsDailyTrendItem,
  type AdmissionsMetricFilters,
} from '../api/admissions'

type AdmissionsDailyTrendProps = {
  filters: AdmissionsMetricFilters
}

type TrendResult = {
  requestKey: string
  endDate: string
  items: AdmissionsDailyTrendItem[]
  startDate: string
}

export function AdmissionsDailyTrend({ filters }: AdmissionsDailyTrendProps) {
  const [response, setResult] = useState<TrendResult | null>(null)
  const [error, setError] = useState<{ requestKey: string; endDate: string; message: string; startDate: string } | null>(
    null,
  )
  const [searchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate

  const [retryCount, setRetryCount] = useState(0)
  const requestKey = JSON.stringify([startDate, endDate, filters, retryCount])

  useEffect(() => {
    let isActive = true

    void getAdmissionsDailyTrend(startDate, endDate, filters)
      .then((items) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey, endDate, items, startDate })
        }
      })
      .catch((requestError: Error) => {
        if (isActive) {
          setError({ requestKey, endDate, message: requestError.message, startDate })
        }
      })

    return () => {
      isActive = false
    }
  }, [endDate, filters, startDate, requestKey])

  const currentError = error?.requestKey === requestKey ? error.message : null
  const result = response?.requestKey === requestKey ? response : null
  const status = {
    loading: result === null && currentError === null,
    error: currentError,
    onRetry: () => setRetryCount((count) => count + 1),
  }


  const blockSize = trendBlockSize(startDate, endDate)
  const items = groupTrendPeriods((result?.items ?? []).map(item => ({ date: item.admission_date, value: item.admission_count })), startDate, blockSize)
  return (
    <LineChart
      {...status}
      items={items}
      title={blockSize === 1 ? 'Daily Admissions' : 'Admissions trend'}
      valueLabel="Admissions"
      variant="bar"
      height={400}
      subtitle={blockSize === 1 ? 'Total admissions each day' : `Total admissions per ${blockSize}-day period. The tooltip shows the exact dates and day count, including any shorter final period.`}
    />
  )
}
