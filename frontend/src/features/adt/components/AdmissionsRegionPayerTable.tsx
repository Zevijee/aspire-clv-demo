import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  formatPayerType,
  getAdmissionsByRegionAndPayer,
  type RegionPayerAdmissionsRow,
  type RegionPayerAdmissionsTable,
} from '../api/admissions'

type TableResult = RegionPayerAdmissionsTable & {
  requestKey: string
  endDate: string
  startDate: string
}

export function AdmissionsRegionPayerTable() {
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

    void getAdmissionsByRegionAndPayer(startDate, endDate)
      .then((table) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey, ...table, endDate, startDate })
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


  const columns: TableColumn<RegionPayerAdmissionsRow>[] = [
    {
      header: 'Region',
      id: 'region',
      initialSortDirection: 'ascending',
      isRowHeader: true,
      value: (row) => row.region,
    },
    ...(result?.payer_types ?? []).map((payerType) => ({
      header: formatPayerType(payerType),
      id: payerType,
      initialSortDirection: 'descending' as const,
      numeric: true,
      format: (value: number | string) => value.toLocaleString(),
      value: (row: RegionPayerAdmissionsRow) => row.admission_counts[payerType] ?? 0,
    })),
  ]

  return (
    <Table
      {...status}
      columns={columns}
      csvFileName={`admissions-by-region-and-payer-${startDate}-to-${endDate}.csv`}
      emptyMessage="No admissions match the selected date range."
      getRowKey={(row) => row.region}
      rows={result?.regions ?? []}
      subtitle="Admissions grouped by operating region and payer type"
      title="Admissions by Region and Payer"
    />
  )
}
