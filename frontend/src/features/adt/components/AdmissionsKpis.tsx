import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Kpis, type KpiTrend } from '../../../shared/components/Kpis'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsKpis,
  type AdmissionsKpiSummary,
  type AdmissionsMetricFilters,
} from '../api/admissions'

type KpiResult = AdmissionsKpiSummary & {
  requestKey: string
  endDate: string
  startDate: string
}

const defaultFilters: AdmissionsMetricFilters = {
  facilities: [],
  payerTypes: [],
  portfolios: [],
  regions: [],
}

function getKpiTrend(
  currentValue: number,
  priorValue: number,
  fractionDigits = 0,
  lowerValueIsBetter = false,
): KpiTrend {
  const difference = Number((currentValue - priorValue).toFixed(fractionDigits))
  const direction = difference === 0 ? 'flat' : difference > 0 ? 'up' : 'down'
  const isFavorable = lowerValueIsBetter ? difference < 0 : difference > 0
  const tone =
    difference === 0
      ? 'neutral'
      : isFavorable
        ? 'positive'
        : 'negative'
  const formattedDifference = Math.abs(difference).toLocaleString(undefined, {
    maximumFractionDigits: fractionDigits,
    minimumFractionDigits: fractionDigits,
  })

  return {
    direction,
    label: 'vs prior period',
    tone,
    value: difference > 0 ? `+${formattedDifference}` : difference < 0 ? `-${formattedDifference}` : '0',
  }
}

function getPercentageTrend(value: number, total: number, label: string): KpiTrend {
  const percentage = total === 0 ? 0 : (value / total) * 100

  return {
    direction: 'flat',
    label,
    tone: 'neutral',
    value: `${percentage.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`,
  }
}

export function AdmissionsKpis({ filters = defaultFilters }: { filters?: AdmissionsMetricFilters }) {
  const [response, setResult] = useState<KpiResult | null>(null)
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
    <Kpis
      {...status}
      items={result === null ? [
        'Total admissions', 'Average per day', 'Readmissions', '30-day readmissions', 'Admission sources',
      ].map((header) => ({ header, value: '\u2014', trend: { direction: 'flat', label: '', tone: 'neutral', value: '' } })) : [
        {
          header: 'Total admissions',
          trend: getKpiTrend(result.total_admissions, result.prior_period.total_admissions),
          value: result.total_admissions.toLocaleString(),
        },
        {
          header: 'Average per day',
          trend: getKpiTrend(
            result.average_admissions_per_day,
            result.prior_period.average_admissions_per_day,
            1,
          ),
          value: result.average_admissions_per_day.toLocaleString(undefined, {
            maximumFractionDigits: 1,
          }),
        },
        {
          header: 'Readmissions',
          trend: getPercentageTrend(
            result.readmission_count,
            result.total_admissions,
            'of total admissions',
          ),
          value: result.readmission_count.toLocaleString(),
        },
        {
          header: '30-day readmissions',
          trend: getPercentageTrend(
            result.readmission_within_30_days_count,
            result.readmission_count,
            'of readmissions',
          ),
          value: result.readmission_within_30_days_count.toLocaleString(),
        },
        {
          header: 'Admission sources',
          trend: getKpiTrend(
            result.unique_admission_source_count,
            result.prior_period.unique_admission_source_count,
          ),
          value: result.unique_admission_source_count.toLocaleString(),
        },
      ]}
    />
  )
}
