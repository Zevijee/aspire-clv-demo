import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { AdmissionsKpis } from './AdmissionsKpis'
import { AdmissionsPayerDistribution } from './AdmissionsPayerDistribution'
import { AdmissionsRegionPayerTable } from './AdmissionsRegionPayerTable'
import {
  getAdmissionsByRegion,
  type RegionAdmissionsRanking,
} from '../api/admissions'

type RankingResult = {
  requestKey: string
  endDate: string
  ranking: { label: string; value: number }[]
  startDate: string
}

export function AdmissionsRegionRanking() {
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

    void getAdmissionsByRegion(startDate, endDate)
      .then((ranking) =>
        ranking.map((item: RegionAdmissionsRanking) => ({
          label: item.region,
          value: item.admission_count,
        })),
      )
      .then((ranking) => {
        if (isActive) {
          setResult({ requestKey, endDate, ranking, startDate })
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
    <>
      <AdmissionsKpis />
      <div className="admissions-dashboard">
        <BarChartRanking
          {...status}
          categoryLabel="Region"
          items={result?.ranking ?? []}
          subtitle="Ranked by admission volume across regions"
          title="Admissions by Region"
          valueLabel="admissions"
        />
        <AdmissionsPayerDistribution />
      </div>
      <AdmissionsRegionPayerTable />
    </>
  )
}
