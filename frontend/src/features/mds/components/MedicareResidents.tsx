import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import {
  downloadMedicareResidents, getMedicareResidents, medicareBase,
  type MedicareResident, type MedicareResidentsQuery,
} from '../api'

const pageSize = 50
const money = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<MedicareResident>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  // A filter only, set by a click on an Overview chart segment: "PT/OT: 0-5"
  // and so on, each matched by the API. A resident can be in several parts.
  { id: 'pdpm-category', header: 'PDPM category', filterable: true, hidden: true, value: () => '' },
  // Labels match the API's filter values exactly.
  { id: 'payer', header: 'Payer', filterable: true,
    value: row => row.payer_type === 'medicare' ? 'Federal Medicare' : 'Managed Medicare PDPM' },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'admission-date', header: 'Admission date', value: row => row.admission_date },
  { id: 'los', header: 'Length of stay', numeric: true, value: row => row.length_of_stay },
  { id: 'ard', header: 'ARD', value: row => row.ard ?? '—' },
  // The value stays the text, so filters, search and export match the API. The
  // ARD is null exactly while the care code is missing, so it marks the label.
  { id: 'pdpm-score', header: 'PDPM score', filterable: true, value: row => row.pdpm_score,
    format: (_, row) => row.ard === null
      ? <span className="care-code-badge care-code-badge--missing">{row.pdpm_score}</span>
      : <span className="care-code">{row.pdpm_score}</span> },
  { id: 'average-rate', header: 'Average rate', numeric: true, value: row => row.average_rate,
    format: (_, row) => money(row.average_rate) },
  { id: 'total-revenue', header: 'Total revenue', numeric: true, value: row => row.total_revenue,
    format: (_, row) => money(row.total_revenue) },
]

/** Every Medicare resident on the census day, paged, sorted and filtered by the API.
 * Opening filters come from residents_* parameters, set when an Overview chart
 * segment is clicked; a new set remounts the table with them. */
export function MedicareResidents() {
  const [params] = useReportSearchParams()
  const initialFilters: Record<string, string[]> = {}
  for (const [key, value] of params) {
    if (key.startsWith('residents_')) (initialFilters[key.slice('residents_'.length)] ??= []).push(value)
  }
  return <MedicareResidentsTable key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function MedicareResidentsTable({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [query, setQuery] = useState<MedicareResidentsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: MedicareResident[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: MedicareResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getMedicareResidents(pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <Table<MedicareResident> {...status}
    title="PDPM residents"
    subtitle={`Everyone paid from their PDPM code${censusDate ? ` on ${censusDate}` : ''}: Federal Medicare and Managed Medicare PDPM. `
      + 'Payer name shows the plan. Length of stay is days since admission. '
      + 'ARD is the 5-day assessment reference date, on day 1-8 of the Medicare stay. '
      + 'PDPM score is the four-letter PDPM code: PT/OT, SLP, nursing and NTA groups; '
      + 'until the assessment is coded, a few days after the ARD, the care code is missing and the ARD blank. '
      + 'Total revenue is PDPM revenue on this payer to date; average rate is that revenue per day on the payer.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'medicare-residents', startDate: censusDate, endDate: censusDate,
      endpoint: `${medicareBase}/residents/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total} initialFilters={initialFilters}
    emptyMessage="No residents match these filters."
    csvFileName={`current-medicare-residents-${censusDate || 'today'}.csv`}
    onExport={() => downloadMedicareResidents(query, censusDate || 'today')}
    footer={<nav aria-label="Resident pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} residents`
          : error ? 'Pagination unavailable' : 'Loading residents…'}
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
