import { useCallback, useEffect, useState } from 'react'
import { LocationName } from '../../../shared/components/LocationName'
import { StatusBadge } from '../../../shared/components/StatusBadge'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { downloadWeights, getWeights, weightsBase, type ResidentWeight, type WeightsPage, type WeightsQuery } from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const pounds = (value: number) => `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} lb`
const signedPounds = (value: number) => `${value > 0 ? '+' : ''}${pounds(value)}`
const signedPercent = (value: number | null) => value === null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(1)}%`
// A loss needs action now; a gain needs watching.
const FLAG_TONES = { 'Significant loss': 'danger', 'Significant gain': 'warning', None: 'neutral' } as const

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<ResidentWeight>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'flag', header: 'Significant change', filterable: true, value: row => row.flag,
    format: (_, row) => <StatusBadge tone={FLAG_TONES[row.flag]}>{row.flag}</StatusBadge> },
  { id: 'admission-date', header: 'Admitted', value: row => row.admission_date, format: (_, row) => day(row.admission_date) },
  { id: 'days', header: 'Days in facility', numeric: true, value: row => row.days_in_facility },
  { id: 'admission-weight', header: 'Admission weight', numeric: true, value: row => row.admission_weight,
    format: (_, row) => pounds(row.admission_weight) },
  { id: 'current-weight', header: 'Current weight', numeric: true, value: row => row.current_weight,
    format: (_, row) => pounds(row.current_weight) },
  { id: 'weighed-on', header: 'Weighed on', value: row => row.weighed_on, format: (_, row) => day(row.weighed_on) },
  // The shared change colours: a gain green, a loss red.
  { id: 'change', header: 'Since admission', numeric: true, value: row => row.change,
    change: { favorable: 'increase' }, format: (_, row) => signedPounds(row.change) },
  { id: 'change-percent', header: 'Since admission %', numeric: true, value: row => row.change_percent,
    change: { favorable: 'increase' }, format: (_, row) => signedPercent(row.change_percent) },
  { id: 'highest', header: 'Highest', numeric: true, value: row => row.highest, format: (_, row) => pounds(row.highest) },
  { id: 'lowest', header: 'Lowest', numeric: true, value: row => row.lowest, format: (_, row) => pounds(row.lowest) },
  { id: 'range', header: 'Highest to lowest', numeric: true, value: row => row.weight_range,
    format: (_, row) => pounds(row.weight_range) },
  { id: 'range-percent', header: 'Highest to lowest %', numeric: true, value: row => row.range_percent,
    format: (_, row) => `${Number(row.range_percent).toFixed(1)}%` },
  { id: 'change-30-days', header: '30-day change', numeric: true, value: row => row.change_30_days ?? '—',
    change: { favorable: 'increase' }, format: (_, row) => signedPercent(row.change_30_days) },
  { id: 'change-180-days', header: '180-day change', numeric: true, value: row => row.change_180_days ?? '—',
    change: { favorable: 'increase' }, format: (_, row) => signedPercent(row.change_180_days) },
]

/** Weight Surveillance: everyone in a bed today -- the latest generated day --
 * with their weights this stay, paged, sorted and filtered by the API.
 * Significant changes first. */
export function WeightSurveillance() {
  const [query, setQuery] = useState<WeightsQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; body: WeightsPage } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  // The day, once known, so filter options describe the same day as the rows.
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: WeightsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getWeights(pageIndex * pageSize, query, null, controller.signal)
      .then(body => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, body })
        setCensusDate(body.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response.body : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))

  return <Table<ResidentWeight> {...status}
    title="Resident weights"
    subtitle={'Everyone in a bed today, with this stay\'s weigh-ins: on admission, weekly for four '
      + 'weeks, then every 30 days. A significant change is the MDS\'s: 5% or more in 30 days, or 10% or more '
      + 'in 180, each against the latest weight at least that long before the current one.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.stay_id}
    initialSort={{ columnId: 'flag', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'weight-surveillance', startDate: censusDate, endDate: censusDate,
      endpoint: `${weightsBase}/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No residents match these filters."
    csvFileName={`weights-${censusDate || 'latest'}.csv`}
    onExport={() => downloadWeights(query, censusDate)}
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
