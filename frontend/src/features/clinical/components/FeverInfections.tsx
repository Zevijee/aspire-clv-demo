import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { Kpis } from '../../../shared/components/Kpis'
import { LocationName } from '../../../shared/components/LocationName'
import { StatusBadge } from '../../../shared/components/StatusBadge'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getInfectionsBoard, type InfectionAlert, type InfectionsBoard } from '../api'

const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const STATUS_LABELS = { outbreak: 'Outbreak', watch: 'Watch' }

const columns: TableColumn<InfectionAlert>[] = [
  { id: 'facility', header: 'Facility', isRowHeader: true, filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  // Outbreaks first, then most cases: the server's order, kept when re-sorted.
  { id: 'status', header: 'Status', filterable: true, value: row => STATUS_LABELS[row.status],
    sortValue: row => (row.status === 'outbreak' ? 0 : 1000) - row.cases_7_days,
    format: (_, row) => <StatusBadge tone={row.status === 'outbreak' ? 'danger' : 'warning'}>
      {STATUS_LABELS[row.status]}</StatusBadge> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'infection-type', header: 'Infection type', filterable: true, value: row => row.infection_type },
  { id: 'cases-72-hours', header: 'New cases, 72 hours', numeric: true, value: row => row.cases_72_hours },
  { id: 'cases-7-days', header: 'New cases, 7 days', numeric: true, value: row => row.cases_7_days },
  { id: 'with-fever', header: 'With fever', numeric: true, value: row => row.with_fever },
  { id: 'active', header: 'Active cases', numeric: true, value: row => row.active },
  { id: 'wings', header: 'Wings affected', value: row => row.wings.join(', ') },
  { id: 'first-onset', header: 'First case', value: row => row.first_onset, format: (_, row) => day(row.first_onset) },
  { id: 'latest-onset', header: 'Latest case', value: row => row.latest_onset, format: (_, row) => day(row.latest_onset) },
]

/** The outbreak alert board: every facility and contagious type whose new
 * cases reach watch or outbreak on the header's day -- the latest generated
 * day unless one is picked -- with the day's totals above. */
export function FeverInfections() {
  const [params] = useReportSearchParams()
  const picked = params.get('date')
  const [response, setResponse] = useState<{ key: string | null; body: InfectionsBoard } | null>(null)
  const [failure, setFailure] = useState<{ key: string | null; message: string } | null>(null)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void getInfectionsBoard(picked, controller.signal)
      .then(body => { if (!controller.signal.aborted) setResponse({ key: picked, body }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setFailure({ key: picked, message: error.message }) })
    return () => controller.abort()
  }, [picked, retry])

  const data = response?.key === picked ? response.body : null
  const error = failure?.key === picked && !data ? failure.message : null
  const status = { loading: data === null && error === null, error, onRetry: () => {
    setFailure(null)
    setRetry(count => count + 1)
  } }
  const count = (value: number) => value.toLocaleString()
  const facilities = data ? `of ${count(data.facilities)} facilities` : ''

  return <>
    <Kpis {...status} items={[
      { header: 'Facilities in outbreak', value: data ? count(data.facilities_in_outbreak) : '',
        trend: { tone: data?.facilities_in_outbreak ? 'negative' : 'positive', value: '', label: facilities } },
      { header: 'Facilities on watch', value: data ? count(data.facilities_on_watch) : '',
        trend: { tone: data?.facilities_on_watch ? 'negative' : 'positive', value: '', label: 'and no outbreak' } },
      { header: 'New cases, 72 hours', value: data ? count(data.new_cases_72_hours) : '',
        trend: { tone: 'neutral', value: '', label: 'Every infection type' } },
      { header: 'Active cases', value: data ? count(data.active_cases) : '',
        trend: { tone: 'neutral', value: '', label: 'Begun and not yet resolved' } },
    ]} />
    <Table<InfectionAlert> {...status}
      title="Outbreak alerts"
      subtitle={'Facilities with a cluster of a contagious infection: respiratory, influenza-like illness or '
        + 'gastrointestinal. Outbreak: 3 or more new cases in 72 hours, or 5 or more in 7 days. Watch: 2 new cases '
        + 'in 72 hours, or 3 or 4 in 7 days. Urinary tract and skin infections and fevers with no known source '
        + 'do not spread between residents and raise no alert.'}
      columns={columns} rows={data?.alerts ?? []} getRowKey={row => `${row.facility_id}:${row.infection_type}`}
      initialSort={{ columnId: 'status', direction: 'ascending' }}
      internalScroll stickyFirstColumn searchable clearableFilters
      emptyMessage="No facility has a cluster of contagious infections on this day."
      csvFileName={`outbreak-alerts-${data?.date ?? 'latest'}.csv`} />
  </>
}
