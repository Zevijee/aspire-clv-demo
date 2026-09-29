import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
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
  { id: 'payer', header: 'Payer', filterable: true, value: row => ({
    medicare: 'Medicare', medicare_hmo: 'Medicare HMO', medicare_comm: 'Commercial Medicare',
  } as Record<string, string>)[row.payer_type] ?? row.payer_type },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'los', header: 'Length of stay', numeric: true, value: row => row.length_of_stay },
  { id: 'pdpm-score', header: 'PDPM score', filterable: true, value: row => row.pdpm_score },
  { id: 'average-rate', header: 'Average rate', numeric: true, value: row => row.average_rate,
    format: (_, row) => money(row.average_rate) },
  { id: 'total-revenue', header: 'Total revenue', numeric: true, value: row => row.total_revenue,
    format: (_, row) => money(row.total_revenue) },
]

/** Every Medicare resident on the census day, paged, sorted and filtered by the API. */
export function MedicareResidents() {
  const [query, setQuery] = useState<MedicareResidentsQuery>({ filters: {}, sort: null, search: '' })
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
    title="Medicare residents"
    subtitle={`Everyone on a Medicare payer${censusDate ? ` on ${censusDate}` : ''}. Length of stay is days since admission. `
      + 'PDPM score is the four-letter PDPM code: PT/OT, SLP, nursing and NTA groups. '
      + 'Total revenue is PDPM revenue on this payer to date; average rate is that revenue per day on the payer.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'medicare-residents', startDate: censusDate, endDate: censusDate,
      endpoint: `${medicareBase}/residents/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
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
