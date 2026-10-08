import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  downloadHistoricalResidents, getHistoricalResidents, historicalResidentFilterOptions,
  type HistoricalResident, type MedicareResidentsQuery,
} from '../api'
import { worksheetDateBasis } from '../worksheetApi'

const pageSize = 50
const money = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<HistoricalResident>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'payer', header: 'Payer', filterable: true, value: row => row.payer_label },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'medicare-start', header: 'Medicare start', value: row => row.medicare_start },
  { id: 'ard', header: 'ARD', value: row => row.ard ?? '—' },
  { id: 'active', header: 'Active', filterable: true, dataType: 'boolean', value: row => row.active },
  { id: 'medicare-days', header: 'Medicare days', numeric: true, value: row => row.medicare_days },
  // The value stays the text, so filters, search and export match the API. The
  // ARD is null exactly while the care code is missing, so it marks the label.
  { id: 'pdpm-score', header: 'PDPM score', filterable: true, value: row => row.pdpm_score,
    format: (_, row) => row.ard === null
      ? <span className="care-code-badge care-code-badge--missing">{row.pdpm_score}</span>
      : <span className="care-code">{row.pdpm_score}</span> },
  { id: 'average-rate', header: 'Average rate', numeric: true, value: row => row.average_rate,
    format: (_, row) => money(row.average_rate) },
  { id: 'neutral-rate', header: 'Neutral rate', numeric: true, value: row => row.neutral_rate,
    format: (_, row) => money(row.neutral_rate) },
  { id: 'total-revenue', header: 'Total revenue', numeric: true, value: row => row.total_revenue,
    format: (_, row) => money(row.total_revenue) },
  { id: 'neutral-revenue', header: 'Neutral revenue', numeric: true, value: row => row.neutral_revenue,
    format: (_, row) => money(row.neutral_revenue) },
]

/** The Residents tab: every Medicare PDPM stay the Overview counts, paged,
 * sorted and filtered by the API. A new date range or date basis starts the
 * table over, on its first page. */
export function HistoricalResidents() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const dateBasis = worksheetDateBasis(params)
  return <HistoricalResidentsTable key={`${startDate}|${endDate}|${dateBasis}`}
    startDate={startDate} endDate={endDate} dateBasis={dateBasis} />
}

function HistoricalResidentsTable({ startDate, endDate, dateBasis }: {
  startDate: string; endDate: string; dateBasis: 'start' | 'ard'
}) {
  const [query, setQuery] = useState<MedicareResidentsQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: HistoricalResident[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: MedicareResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getHistoricalResidents(startDate, endDate, dateBasis, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, dateBasis, pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const basis = dateBasis === 'ard' ? 'whose 5-day ARD falls' : 'that started'
  return <Table<HistoricalResident> {...status}
    title="PDPM stays"
    subtitle={`Every Medicare PDPM stay ${basis} from ${startDate} to ${endDate}: Federal Medicare and Managed `
      + 'Medicare PDPM, the stays the Overview counts. Payer name shows the plan. Medicare days run through '
      + `the stay's end, or ${censusDate || 'the census day'} while it is active. ARD is the 5-day assessment `
      + 'reference date; until the assessment is coded the care code is missing and the ARD blank. Revenue is '
      + 'every day of the stay at its PDPM rate; neutral revenue the same days at the national per diem times '
      + 'the PDPM day factor. The rates are each revenue per Medicare day.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.payer_stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'historical-medicare-residents', startDate, endDate,
      endpoint: historicalResidentFilterOptions(dateBasis) }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No stays match these filters."
    csvFileName={`historical-medicare-pdpm-residents-${startDate}-to-${endDate}-by-${dateBasis}.csv`}
    onExport={() => downloadHistoricalResidents(startDate, endDate, dateBasis, query)}
    footer={<nav aria-label="Stay pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} stays`
          : error ? 'Pagination unavailable' : 'Loading stays…'}
      </span>
      <div className="report-table__pagination-actions">
        {[
          { label: 'First page', symbol: '«', index: 0, disabled: pageIndex === 0 },
          { label: 'Previous page', symbol: '‹', index: pageIndex - 1, disabled: pageIndex === 0 },
          { label: 'Next page', symbol: '›', index: pageIndex + 1, disabled: pageIndex + 1 >= pageCount },
          { label: 'Last page', symbol: '»', index: pageCount - 1, disabled: pageIndex + 1 >= pageCount },
        ].map(({ label, symbol, index, disabled }) => <button key={label} type="button"
          className="report-table__pagination-arrow" aria-label={label} title={label}
          disabled={status.loading || !!error || disabled} onClick={() => setPage({ queryKey, index })}>
          <span aria-hidden="true">{symbol}</span>
        </button>)}
      </div>
    </nav>}
  />
}
