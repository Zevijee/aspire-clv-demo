import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsKpis,
  type AdmissionsKpiSummary,
  type AdmissionsMetricFilters,
} from '../api/admissions'

type DistributionResult = AdmissionsKpiSummary & {
  requestKey: string
  endDate: string
  startDate: string
}

type AdmissionsReadmissionsDistributionProps = {
  filters: AdmissionsMetricFilters
}

export function AdmissionsReadmissionsDistribution({
  filters,
}: AdmissionsReadmissionsDistributionProps) {
  const [response, setResult] = useState<DistributionResult | null>(null)
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

    void getAdmissionsKpis(startDate, endDate, filters)
      .then((summary) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey, ...summary, endDate, startDate })
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


  return (
    <DonutChart
      {...status}
      items={result === null ? [] : [
        {
          label: 'Admissions',
          value: result.total_admissions - result.readmission_count,
        },
        {
          label: 'Readmissions within 30 days',
          value: result.readmission_within_30_days_count,
        },
        {
          label: 'Readmissions',
          value: result.readmission_count - result.readmission_within_30_days_count,
        },
      ]}
      subtitle="Percentage of total admissions"
      title="Admissions vs Readmissions"
    />
  )
}
