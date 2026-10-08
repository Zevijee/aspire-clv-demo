import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { payerLabel, payerLabels } from '../../adt/api/admissionsOverview'
import {
  SEVERITY_LEVELS, downloadIncidentLogs, getIncidentLogs, incidentLogsBase, type IncidentLog, type IncidentLogsQuery,
} from '../api'
import { INCIDENT_PAYER_PARAM, INCIDENT_SEVERITY_PARAM, INCIDENT_TYPE_PARAM } from './IncidentFilters'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
// The hour as a clock time: 0 is 12 AM, 13 is 1 PM.
const clock = (hour: number) => `${hour % 12 === 0 ? 12 : hour % 12} ${hour < 12 ? 'AM' : 'PM'}`
// The Overview's drilldown, one level per location filter, in path order.
const locationFilters = ['state', 'portfolio', 'region', 'facility']

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<IncidentLog>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'incident-date', header: 'Incident date', initialSortDirection: 'descending',
    value: row => row.incident_date, format: (_, row) => day(row.incident_date) },
  { id: 'hour', header: 'Time', numeric: true, value: row => row.hour, format: (_, row) => clock(row.hour) },
  { id: 'time-of-day', header: 'Time of day', filterable: true, value: row => row.time_of_day },
  { id: 'incident-type', header: 'Incident type', filterable: true, value: row => row.incident_type },
  { id: 'severity', header: 'Severity', filterable: true, value: row => row.severity },
  // Yes is the outcome to bring down, so it reads red.
  { id: 'hospitalized', header: 'Resulted in hospitalization', filterable: true, dataType: 'boolean',
    negativeWhenTrue: true, value: row => row.hospitalized },
  // An open investigation is outstanding work, so Yes reads red too.
  { id: 'still-open', header: 'Still open', filterable: true, dataType: 'boolean', negativeWhenTrue: true,
    value: row => row.still_open },
  { id: 'closed-date', header: 'Closed date', value: row => row.closed_date, format: (_, row) => day(row.closed_date) },
  { id: 'payer', header: 'Payer type', filterable: true, value: row => payerLabel(row.payer_type) },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
]

/** The Logs tab: every incident in the date range, paged, sorted and filtered by
 * the API. It opens on the Overview's selection -- its drilldown location and
 * its payer, type and severity filters -- so it lists the incidents the
 * Overview counted. */
export function IncidentLogs() {
  const [params] = useReportSearchParams()
  const initialFilters: Record<string, string[]> = {}
  params.getAll('drill').forEach((name, index) => { initialFilters[locationFilters[index]] = [name] })
  const payers = params.getAll(INCIDENT_PAYER_PARAM).map(payer => payerLabels[payer] ?? payer)
  if (payers.length) initialFilters.payer = payers
  const types = params.getAll(INCIDENT_TYPE_PARAM)
  if (types.length) initialFilters['incident-type'] = types
  const severities = params.getAll(INCIDENT_SEVERITY_PARAM).map(level => SEVERITY_LEVELS[level] ?? level)
  if (severities.length) initialFilters.severity = severities
  return <IncidentLogsContent key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function IncidentLogsContent({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const [query, setQuery] = useState<IncidentLogsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify([startDate, endDate, query])
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: IncidentLog[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const onQueryChange = useCallback((next: IncidentLogsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getIncidentLogs(startDate, endDate, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResponse({ key: requestKey, items: data.items, total: data.total })
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <Table<IncidentLog> {...status}
    title="Incident logs"
    subtitle={'Every resident incident in the date range. Time of day groups the hour: morning 6 AM to noon, '
      + 'afternoon noon to 6 PM, evening 6 to 10 PM, night 10 PM to 6 AM. Still open means its investigation had '
      + 'not closed by the latest day.'}
    columns={columns} rows={result?.items ?? []} getRowKey={row => row.incident_id}
    initialSort={{ columnId: 'incident-date', direction: 'descending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    initialFilters={initialFilters}
    filterSource={{ id: 'incidents', startDate, endDate, endpoint: `${incidentLogsBase}/filter-options` }}
    onQueryChange={onQueryChange} totalRows={result?.total}
    emptyMessage="No incidents match the selected dates and filters."
    csvFileName={`incidents-${startDate}-to-${endDate}.csv`}
    onExport={() => downloadIncidentLogs(startDate, endDate, query)}
    footer={<nav aria-label="Incident log pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} incidents`
          : error ? 'Pagination unavailable' : 'Loading incidents…'}
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
