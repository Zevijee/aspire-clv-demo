import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { payerLabel } from '../../adt/api/admissionsOverview'
import {
  censusBase, downloadCensusResidents, getCensusResidents,
  type CensusResident, type CensusResidentsQuery,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const rate = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<CensusResident>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'admission-date', header: 'Admission date', value: row => row.admission_date,
    format: (_, row) => day(row.admission_date) },
  { id: 'days', header: 'Days in facility', numeric: true, value: row => row.days_in_facility },
  { id: 'readmission', header: 'Readmission', filterable: true, dataType: 'boolean',
    value: row => row.is_readmission ? 'Yes' : 'No' },
  { id: 'care-level', header: 'Care level', filterable: true, value: row => row.care_level },
  { id: 'payer', header: 'Payer type', filterable: true, value: row => payerLabel(row.payer_type) },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'skilled', header: 'Skilled', filterable: true, dataType: 'boolean',
    value: row => row.is_skilled ? 'Yes' : 'No' },
  { id: 'payer-since', header: 'Payer since', value: row => row.payer_since,
    format: (_, row) => day(row.payer_since) },
  { id: 'daily-rate', header: 'Daily rate', numeric: true, value: row => row.daily_rate,
    format: (_, row) => rate(row.daily_rate) },
]

/** Everyone in a bed on the census day, paged, sorted and filtered by the API. */
export function CensusResidents() {
  const [query, setQuery] = useState<CensusResidentsQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: CensusResident[]; total: number; censusDate: string } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  // The census day, once known, so filter options describe the same day as the rows.
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: CensusResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getCensusResidents(pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total, censusDate: data.census_date })
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
  return <Table<CensusResident> {...status}
    title="Residents"
    subtitle={censusDate ? `Everyone in a bed at the close of ${day(censusDate)}. Daily rate is that day's, after PDPM for skilled payers.`
      : 'Everyone in a bed on the census day.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'census-residents', startDate: censusDate, endDate: censusDate,
      endpoint: `${censusBase}/residents/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No residents match these filters."
    csvFileName={`census-residents-${censusDate || 'today'}.csv`}
    onExport={() => downloadCensusResidents(query, censusDate || 'today')}
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
