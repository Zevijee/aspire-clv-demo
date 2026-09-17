import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  getAdmissionsByRegionLevelMetrics,
  getAdmissionsByRegionMetrics,
  type RegionAdmissionsMetrics,
} from '../api/admissions'
import { AdmissionsPortfolioKpis } from './AdmissionsPortfolioKpis'

type TableResult = {
  requestKey: string
  endDate: string
  rows: RegionAdmissionsMetrics[]
  startDate: string
}

type RegionalMetricsTableRow = RegionAdmissionsMetrics & {
  portfolio?: string
  rowType: 'region' | 'state-total'
}

const stateDisplayOrder = ['Texas', 'Florida', 'Pennsylvania']

const regionColumns: TableColumn<RegionalMetricsTableRow>[] = [
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
    value: (row) => row.portfolio ?? '',
  },
  {
    filterable: true,
    header: 'Region',
    id: 'region',
    isRowHeader: true,
    value: (row) => row.region,
  },
  {
    filterable: true,
    header: 'Facilities',
    id: 'facility-count',
    numeric: true,
    format: (value) => value.toLocaleString(),
    value: (row) => row.facility_count,
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

function getDaysInRange(startDate: string, endDate: string) {
  const start = new Date(`${startDate}T00:00:00Z`)
  const end = new Date(`${endDate}T00:00:00Z`)

  return Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1
}

function sumMetrics(
  rows: RegionalMetricsTableRow[],
  daysInRange: number,
  region: string,
  state: string,
): RegionalMetricsTableRow {
  const totals = rows.reduce(
    (total, row) => ({
      admissions_change: total.admissions_change + row.admissions_change,
      facility_count: total.facility_count + row.facility_count,
      medicare_admission_count: total.medicare_admission_count + row.medicare_admission_count,
      medicare_admissions_change: total.medicare_admissions_change + row.medicare_admissions_change,
      prior_period_admissions: total.prior_period_admissions + row.prior_period_admissions,
      prior_period_medicare_admission_count:
        total.prior_period_medicare_admission_count + row.prior_period_medicare_admission_count,
      readmission_count: total.readmission_count + row.readmission_count,
      region_count: total.region_count + row.region_count,
      total_admissions: total.total_admissions + row.total_admissions,
    }),
    {
      admissions_change: 0,
      facility_count: 0,
      medicare_admission_count: 0,
      medicare_admissions_change: 0,
      prior_period_admissions: 0,
      prior_period_medicare_admission_count: 0,
      readmission_count: 0,
      region_count: 0,
      total_admissions: 0,
    },
  )

  return {
    ...totals,
    referring_hospitals: [...new Set(rows.flatMap((row) => row.referring_hospitals))],
    average_admissions_per_day: totals.total_admissions / daysInRange,
    region,
    rowType: 'state-total',
    state,
  }
}

function createStateGroupedRows(
  rows: RegionAdmissionsMetrics[],
  daysInRange: number,
): RegionalMetricsTableRow[] {
  const regionsByState = new Map<string, RegionalMetricsTableRow[]>()

  for (const row of rows) {
    const stateRows = regionsByState.get(row.state) ?? []
    stateRows.push({ ...row, rowType: 'region' })
    regionsByState.set(row.state, stateRows)
  }

  return [...regionsByState.entries()]
    .sort(([leftState], [rightState]) => {
      const leftIndex = stateDisplayOrder.indexOf(leftState)
      const rightIndex = stateDisplayOrder.indexOf(rightState)

      if (leftIndex === -1 || rightIndex === -1) {
        return leftState.localeCompare(rightState)
      }

      return leftIndex - rightIndex
    })
    .flatMap(([state, stateRows]) => {
      const sortedStateRows = [...stateRows].sort((left, right) =>
        left.region.localeCompare(right.region),
      )

      return sortedStateRows.length === 1
        ? sortedStateRows
        : [...sortedStateRows, sumMetrics(sortedStateRows, daysInRange, `${state} total`, state)]
    })
}

type AdmissionsRegionMetricsTableProps = {
  level?: 'portfolio' | 'region'
  payerTypes?: string[]
}

const emptyPayerTypes: string[] = []

export function AdmissionsRegionMetricsTable({
  level = 'portfolio',
  payerTypes = emptyPayerTypes,
}: AdmissionsRegionMetricsTableProps) {
  const [response, setResult] = useState<TableResult | null>(null)
  const [error, setError] = useState<{ requestKey: string; message: string } | null>(
    null,
  )
  const [searchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate
  const [retryCount, setRetryCount] = useState(0)
  const requestKey = JSON.stringify([level, startDate, endDate, payerTypes, retryCount])

  useEffect(() => {
    let isActive = true

    void (
      level === 'portfolio'
        ? getAdmissionsByRegionMetrics(startDate, endDate, level, payerTypes)
        : getAdmissionsByRegionLevelMetrics(startDate, endDate)
    )
      .then((rows) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey, endDate, rows: rows as RegionAdmissionsMetrics[], startDate })
        }
      })
      .catch((requestError: Error) => {
        if (isActive) {
          setError({ requestKey, message: requestError.message })
        }
      })

    return () => {
      isActive = false
    }
  }, [endDate, level, payerTypes, startDate, requestKey, retryCount])

  const currentError = error?.requestKey === requestKey ? error.message : null
  const result = response?.requestKey === requestKey ? response : null
  const status = {
    loading: result === null && currentError === null,
    error: currentError,
    onRetry: () => setRetryCount((count) => count + 1),
  }


  const daysInRange = getDaysInRange(startDate, endDate)
  const columns: TableColumn<RegionalMetricsTableRow>[] = [
    {
      header: level === 'portfolio' ? 'Portfolio' : 'Region',
      id: 'region',
      isRowHeader: true,
      sortable: false,
      value: (row) => row.region,
    },
    ...(level === 'region'
      ? [
          {
            header: 'Portfolio',
            id: 'portfolio',
            sortable: false,
            value: (row: RegionalMetricsTableRow) => row.portfolio ?? '',
          },
        ]
      : []),
    {
      header: 'State',
      id: 'state',
      sortable: false,
      value: (row) => row.state,
    },
    ...(level === 'portfolio'
      ? [
          {
            header: 'Regions',
            id: 'region-count',
            numeric: true,
            sortable: false,
            format: (value: number | string) => value.toLocaleString(),
            value: (row: RegionalMetricsTableRow) => row.region_count,
          },
        ]
      : []),
    {
      header: 'Facilities',
      id: 'facility-count',
      numeric: true,
      sortable: false,
      format: (value) => value.toLocaleString(),
      value: (row) => row.facility_count,
    },
    {
      header: 'Total admissions',
      id: 'total-admissions',
      numeric: true,
      sortable: false,
      format: (value) => value.toLocaleString(),
      value: (row) => row.total_admissions,
    },
    {
      header: 'Average per day',
      id: 'average-per-day',
      numeric: true,
      sortable: false,
      format: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }),
      value: (row) => row.average_admissions_per_day,
    },
    {
      header: 'Average per facility',
      id: 'average-per-facility',
      numeric: true,
      sortable: false,
      format: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }),
      value: (row) => row.total_admissions / row.facility_count,
    },
    {
      header: 'Average per facility per day',
      id: 'average-per-facility-per-day',
      numeric: true,
      sortable: false,
      format: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }),
      value: (row) => row.total_admissions / row.facility_count / daysInRange,
    },
    {
      header: 'Readmissions',
      id: 'readmissions',
      numeric: true,
      sortable: false,
      format: (value) => value.toLocaleString(),
      value: (row) => row.readmission_count,
    },
    {
      header: 'Prior-period admissions',
      id: 'prior-period-admissions',
      numeric: true,
      sortable: false,
      format: (value) => value.toLocaleString(),
      value: (row) => row.prior_period_admissions,
    },
    {
      header: 'Admissions vs Prior',
      id: 'admissions-change',
      numeric: true,
      sortable: false,
      change: { favorable: 'increase' },
      value: (row) => row.admissions_change,
    },
  ]
  const rows: RegionalMetricsTableRow[] = level === 'region'
    ? (result?.rows ?? []).map((row) => ({ ...row, rowType: 'region' }))
    : createStateGroupedRows(result?.rows ?? [], daysInRange)

  return (
    <>
      {level === 'portfolio' && <AdmissionsPortfolioKpis {...status} rows={result?.rows ?? []} />}
      <Table
        {...status}
        columns={level === 'region' ? regionColumns : columns}
        csvFileName={`${level}-admissions-metrics-${startDate}-to-${endDate}.csv`}
        emptyMessage="No admissions match the selected date range."
        getFooterRow={(visibleRows) => {
          if (level === 'region') {
            return null
          }

          const regionRows = visibleRows.filter((row) => row.rowType === 'region')

          if (regionRows.length === 0) {
            return null
          }

          return sumMetrics(regionRows, daysInRange, 'Total', 'All states')
        }}
        getRowKey={(row) => JSON.stringify([row.state, row.portfolio, row.region, row.rowType])}
        getRowClassName={(row) =>
          row.rowType === 'state-total' ? 'regional-admissions-metrics__state-total' : undefined
        }
        internalScroll={level === 'region'}
        rows={rows}
        subtitle={`Current-period admissions metrics with prior-period comparison by ${level}`}
        title={level === 'portfolio' ? 'Portfolio Admissions Metrics' : 'Region Admissions Metrics'}
      />
    </>
  )
}
