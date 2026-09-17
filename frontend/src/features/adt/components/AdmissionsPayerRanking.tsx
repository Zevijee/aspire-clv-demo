import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  formatPayerType,
  getAdmissionsByPayer,
  type PayerAdmissionsDistribution,
} from '../api/admissions'

type RankingResult = {
  requestKey: string
  endDate: string
  items: { label: string; value: number }[]
  startDate: string
}

export function AdmissionsPayerRanking() {
  const [response, setResult] = useState<RankingResult | null>(null)
  const [error, setError] = useState<{ requestKey: string; endDate: string; message: string; startDate: string } | null>(
    null,
  )
  const [searchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate

  const [retryCount, setRetryCount] = useState(0)
  const requestKey = JSON.stringify([startDate, endDate, retryCount])

  useEffect(() => {
    let isActive = true

    void getAdmissionsByPayer(startDate, endDate)
      .then((ranking) =>
        ranking.map((item: PayerAdmissionsDistribution) => ({
          label: formatPayerType(item.payer_type),
          value: item.admission_count,
        })),
      )
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
  }, [endDate, startDate, requestKey])

  const currentError = error?.requestKey === requestKey ? error.message : null
  const result = response?.requestKey === requestKey ? response : null
  const status = {
    loading: result === null && currentError === null,
    error: currentError,
    onRetry: () => setRetryCount((count) => count + 1),
  }


  return (
    <BarChartRanking
      {...status}
      categoryLabel="Payer type"
      items={result?.items ?? []}
      subtitle="Ranked by admission volume across payer types"
      title="Admissions by Payer Type"
      valueLabel="admissions"
    />
  )
}
