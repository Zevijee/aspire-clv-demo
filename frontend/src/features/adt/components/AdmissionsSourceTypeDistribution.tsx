import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsBySourceType,
  type AdmissionsMetricFilters,
  type AdmissionSourceTypeDistribution,
} from '../api/admissions'

type DistributionResult = {
  requestKey: string
  endDate: string
  items: { label: string; value: number }[]
  startDate: string
}

const defaultFilters: AdmissionsMetricFilters = {
  facilities: [],
  payerTypes: [],
  portfolios: [],
  regions: [],
}

export function AdmissionsSourceTypeDistribution({
  filters = defaultFilters,
  selectedSources = [], onChangeSources,
}: {
  filters?: AdmissionsMetricFilters
  selectedSources?: string[]
  onChangeSources?: (sources: string[]) => void
}) {
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

    void getAdmissionsBySourceType(startDate, endDate, filters)
      .then((distribution) =>
        distribution.map((item: AdmissionSourceTypeDistribution) => ({
          label: item.admission_source_type,
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
  }, [endDate, filters, startDate, requestKey])

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
      selectedLabels={selectedSources}
      onSelect={onChangeSources ? (source) => onChangeSources(selectedSources.includes(source)
        ? selectedSources.filter((value) => value !== source) : [...selectedSources, source]) : undefined}
      onClear={onChangeSources ? () => onChangeSources([]) : undefined}
      categoryLabel="Admission source type"
      items={result?.items ?? []}
      subtitle={selectedSources.length ? `Report filtered by ${selectedSources.join(', ')}` : onChangeSources ? 'Click sources to filter the report' : 'Admissions by source type'}
      title="Admissions by Source Type"
      valueLabel="Admissions"
    />
  )
}
