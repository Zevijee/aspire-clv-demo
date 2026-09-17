import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsByFacilityMetrics,
  type FacilityAdmissionsMetrics,
} from '../api/admissions'

type TableResult = {
  requestKey: string
  endDate: string
  rows: FacilityAdmissionsMetrics[]
  startDate: string
}

export function AdmissionsFacilityMetricsTable() {
  const [response, setResult] = useState<TableResult | null>(null)
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

    void getAdmissionsByFacilityMetrics(startDate, endDate)
      .then((rows) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey, endDate, rows, startDate })
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


  const columns: TableColumn<FacilityAdmissionsMetrics>[] = [
    {
      filterable: true,
      header: 'State',
      id: 'state',
      value: (row) => row.state,
    },
    {
      filterable: true,
      header: 'Portfolio',
      id: 'portfolio',
      value: (row) => row.portfolio,
    },
    { filterable: true, header: 'Region', id: 'region', value: (row) => row.region },
    {
      filterable: true,
      header: 'Facility name',
      id: 'facility-name',
      isRowHeader: true,
      value: (row) => row.facility_name,
    },
    {
      filterable: true,
      header: 'Admissions',
      id: 'total-admissions',
      numeric: true,
      format: (value) => value.toLocaleString(),
      value: (row) => row.total_admissions,
    },
    {
      filterable: true,
      header: 'Avg/day',
      id: 'average-per-day',
      numeric: true,
      format: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }),
      value: (row) => row.average_admissions_per_day,
    },
    {
      filterable: true,
      header: 'Readmits',
      id: 'readmissions',
      numeric: true,
      format: (value) => value.toLocaleString(),
      value: (row) => row.readmission_count,
    },
    {
      filterable: true,
      header: 'Prior admissions',
      id: 'prior-period-admissions',
      numeric: true,
      format: (value) => value.toLocaleString(),
      value: (row) => row.prior_period_admissions,
    },
    {
      filterable: true,
      header: 'Admissions change',
      id: 'admissions-change',
      numeric: true,
      change: { favorable: 'increase' },
      value: (row) => row.admissions_change,
    },
  ]

  return (
    <Table
      {...status}
      columns={columns}
      csvFileName={`facility-admissions-metrics-${startDate}-to-${endDate}.csv`}
      emptyMessage="No facilities are available."
      getRowKey={(row) => row.facility_name}
      internalScroll
      rows={result?.rows ?? []}
      searchable
      subtitle="Current-period admissions metrics with prior-period comparison by facility"
      title="Facility Admissions Metrics"
    />
  )
}
