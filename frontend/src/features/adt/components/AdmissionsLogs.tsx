import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getAdmissionLogsFilters } from '../utils/admissionsLogNavigation'
import {
  formatPayerType,
  getRecentAdmissions,
  type Admission,
  type AdmissionsLogsQuery,
} from '../api/admissions'

type LogsResult = {
  requestKey: string
  endDate: string
  logs: Admission[]
  queryKey: string
  startDate: string
  total: number
}

const pageSize = 50
const admissionDateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
})

type PageState = {
  endDate: string
  index: number
  queryKey: string
  startDate: string
}

const columns: TableColumn<Admission>[] = [
  {
    header: 'Resident',
    id: 'resident',
    isRowHeader: true,
    value: (admission) => admission.resident_name,
  },
  {
    filterable: true,
    header: 'Facility',
    id: 'facility',
    value: (admission) => admission.facility_name,
  },
  { header: 'State', id: 'state', filterable: true, value: (admission) => admission.state ?? 'Unavailable' },
  { header: 'Region', id: 'region', filterable: true, value: (admission) => admission.region ?? 'Unavailable' },
  { header: 'Portfolio', id: 'portfolio', filterable: true, value: (admission) => admission.portfolio ?? 'Unavailable' },
  {
    header: 'Admission date',
    id: 'admission-date',
    initialSortDirection: 'descending',
    value: (admission) => admission.admission_date,
    format: (_, admission) => admissionDateFormat.format(new Date(`${admission.admission_date}T00:00:00Z`)).replace(/^Tue,/, 'Tues,'),
  },

  {
    filterable: true,
    header: 'Payer type',
    id: 'payer',
    value: (admission) => formatPayerType(admission.payer_type),
  },
  {
    filterable: true,
    header: 'Payer name',
    id: 'payer-name',
    value: (admission) => admission.payer_name,
  },
  {
    filterable: true,
    header: 'Admission source type',
    id: 'source-type',
    value: (admission) => admission.admission_source_type,
  },
  {
    filterable: true,
    header: 'Admission source name',
    id: 'admission-source',
    value: (admission) => admission.admission_source_name,
  },
  {
    filterable: true,
    header: 'Readmission',
    dataType: 'boolean',
    negativeWhenTrue: true,
    id: 'readmission',
    value: (admission) => admission.is_readmission === true ? 'Yes' : admission.is_readmission === false ? 'No' : 'Unavailable',
  },
]

export function AdmissionsLogs() {
  const [searchParams] = useSearchParams()
  const initialFilters = getAdmissionLogsFilters(searchParams)
  return <AdmissionsLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function AdmissionsLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [response, setResult] = useState<LogsResult | null>(null)
  const [error, setError] = useState<{ requestKey: string; endDate: string; message: string; startDate: string } | null>(
    null,
  )
  const [pageState, setPageState] = useState<PageState>({
    endDate: '',
    index: 0,
    queryKey: '',
    startDate: '',
  })
  const [tableQuery, setTableQuery] = useState<AdmissionsLogsQuery>({ filters: initialFilters, sort: null, search: '' })
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate
  const queryKey = JSON.stringify(tableQuery)
  const pageIndex =
    pageState.startDate === startDate &&
    pageState.endDate === endDate &&
    pageState.queryKey === queryKey
      ? pageState.index
      : 0
  const handleTableQueryChange = useCallback((nextQuery: AdmissionsLogsQuery) => {
    setTableQuery((currentQuery) =>
      JSON.stringify(currentQuery) === JSON.stringify(nextQuery) ? currentQuery : nextQuery,
    )
  }, [])

  const [retryCount, setRetryCount] = useState(0)
  const requestKey = JSON.stringify([startDate, endDate, queryKey, pageIndex, retryCount])

  useEffect(() => {
    let isActive = true

    void getRecentAdmissions(startDate, endDate, pageIndex * pageSize, tableQuery)
      .then((page) => {
        if (isActive) {
          setError(null)
          setResult({ requestKey,
            endDate,
            logs: page.items,
            queryKey,
            startDate,
            total: page.total,
          })
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
  }, [endDate, pageIndex, queryKey, startDate, tableQuery, requestKey])

  const currentError = error?.requestKey === requestKey ? error.message : null
  const result = response?.requestKey === requestKey ? response : null
  const status = {
    loading: result === null && currentError === null,
    error: currentError,
    onRetry: () => setRetryCount((count) => count + 1),
  }


  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))

  return (
    <Table
      {...status}
      getExportRows={async () => {
        const page = await getRecentAdmissions(startDate, endDate, 0, tableQuery, true)
        if (page.items.length !== page.total) throw new Error('Incomplete export')
        return page.items
      }}
      columns={columns}
      initialFilters={initialFilters}
      clearableFilters
      onClearFilters={() => {
        const params = new URLSearchParams(searchParams)
        let changed = false
        for (const key of [...params.keys()]) {
          if (key.startsWith('logs_')) {
            params.delete(key)
            changed = true
          }
        }
        if (changed) setSearchParams(params)
      }}
      csvFileName={`admission-logs-${startDate}-to-${endDate}.csv`}
      emptyMessage="No admissions match the selected date range."
      footer={
        <nav aria-label="Admission log pagination" className="report-table__pagination">
          <span className="report-table__pagination-summary" role="status" aria-live="polite">
            {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} admissions`
              : status.error ? 'Pagination unavailable' : 'Loading admissions…'}
          </span>
          <div className="report-table__pagination-actions">
          {[
            { label: 'First page', symbol: '«', index: 0, disabled: pageIndex === 0 },
            { label: 'Previous page', symbol: '‹', index: pageIndex - 1, disabled: pageIndex === 0 },
            { label: 'Next page', symbol: '›', index: pageIndex + 1, disabled: pageIndex + 1 >= pageCount },
            { label: 'Last page', symbol: '»', index: pageCount - 1, disabled: pageIndex + 1 >= pageCount },
          ].map(({ label, symbol, index, disabled }) => (
            <button key={label} className="report-table__pagination-arrow"
              aria-label={label} title={label} type="button"
              disabled={status.loading || !!status.error || disabled}
              onClick={() => setPageState({ endDate, index, queryKey, startDate })}>
              <span aria-hidden="true">{symbol}</span>
            </button>
          ))}
          </div>
        </nav>
      }
      getRowKey={(admission) => admission.admission_id}
      internalScroll
      stickyFirstColumn
      filterSource={{ id: 'admissions', startDate, endDate }}
      onQueryChange={handleTableQueryChange}
      rows={result?.logs ?? []}
      searchable
      serverSide
      totalRows={result?.total}
      subtitle="Individual admissions in the selected date range"
      title="Admission Logs"
    />
  )
}
