import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { ResidentModal } from './ResidentModal'
import {
  censusBase, downloadResidentSummaries, getResidentSummaries,
  type CensusResidentsQuery, type ResidentSummary,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns = (onOpen: (row: ResidentSummary) => void): TableColumn<ResidentSummary>[] => [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name,
    format: (_, row) => <button type="button" className="drilldown-table__link" onClick={() => onOpen(row)}>
      {row.resident_name}</button> },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'days', header: 'Days in facility', numeric: true, value: row => row.days_in_facility },
  { id: 'stays', header: 'Stays', numeric: true, value: row => row.stays },
  { id: 'admissions', header: 'Admissions', numeric: true, value: row => row.admissions },
  { id: 'discharges', header: 'Discharges', numeric: true, value: row => row.discharges },
  { id: 'current', header: 'Currently in facility', filterable: true, dataType: 'boolean',
    value: row => row.is_current ? 'Yes' : 'No' },
  { id: 'payers', header: 'Payers', numeric: true, value: row => row.payers },
]

/** Every resident ever admitted, totalled across all their stays. */
export function ResidentsReport() {
  const [query, setQuery] = useState<CensusResidentsQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: ResidentSummary[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [asOf, setAsOf] = useState('')
  const [opened, setOpened] = useState<ResidentSummary | null>(null)
  const onQueryChange = useCallback((next: CensusResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getResidentSummaries(pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        if (data.as_of) setAsOf(data.as_of)
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
  return <>
  <Table<ResidentSummary> {...status}
    title="Residents"
    subtitle={'Every resident ever admitted, totalled across all their stays. Days count every day in a bed'
      + (asOf ? `, through ${dateFormat.format(new Date(`${asOf}T00:00:00Z`))}` : '')
      + '. Payers counts distinct payer plans.'}
    columns={columns(setOpened)} rows={result?.items ?? []} getRowKey={row => row.resident_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'resident-summaries', startDate: asOf, endDate: asOf,
      endpoint: `${censusBase}/resident-summaries/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No residents match these filters."
    csvFileName="residents.csv"
    onExport={() => downloadResidentSummaries(query)}
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
  <ResidentModal resident={opened} onClose={() => setOpened(null)} />
  </>
}
