import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { payerLabels } from '../../adt/api/admissionsOverview'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { groupTrendPeriods, trendBlockSize } from '../../../shared/utils/trendPeriods'
import {
  SEVERITY_LEVELS, getDailyIncidents, getIncidents, type DailyIncidents, type FacilityIncidents, type IncidentsReport,
} from '../api'
import { INCIDENT_PAYER_PARAM, INCIDENT_SEVERITY_PARAM, INCIDENT_TYPE_PARAM } from './IncidentFilters'

type Row = DrilldownRow<FacilityIncidents>
type Summed = 'incidents' | 'hospitalized' | 'still_open' | 'morning' | 'afternoon' | 'evening' | 'night' | 'resident_days'

const sum = (row: Row, field: Summed) => row.facilities.reduce((total, facility) => total + facility[field], 0)
// Sums at this scope divided once: never an average of facility rates.
function metric(row: Row, id: string): number | null {
  if (id === 'rate') {
    const days = sum(row, 'resident_days')
    return days > 0 ? sum(row, 'incidents') / days * 1000 : null
  }
  return sum(row, id as Summed)
}

const metrics: [id: string, header: string, digits: number][] = [
  ['incidents', 'Incidents', 0],
  ['hospitalized', 'Resulted in hospitalization', 0],
  ['still_open', 'Still open', 0],
  // When it happened, by the hour.
  ['morning', 'Morning', 0],
  ['afternoon', 'Afternoon', 0],
  ['evening', 'Evening', 0],
  ['night', 'Night', 0],
  ['rate', 'Incidents per 1,000 resident days', 2],
]

/** Incidents: resident incidents in the header's date range, drilled from state
 * to facility -- how many, how many resulted in a hospitalization, how many are still open, when in the
 * day they happened, and the
 * rate per 1,000 resident days. The drilldown is kept in the URL. */
export function Incidents() {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // One drill= per level, in order.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<IncidentsReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const payerFilter = useSearchParamList(INCIDENT_PAYER_PARAM)
  const typeFilter = useSearchParamList(INCIDENT_TYPE_PARAM)
  const severityFilter = useSearchParamList(INCIDENT_SEVERITY_PARAM)
  // Joined, so the fetch reruns only when a filter changes.
  const filterKey = JSON.stringify([payerFilter.values, typeFilter.values, severityFilter.values])
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getIncidents(startDate, endDate, payerFilter.values, typeFilter.values, severityFilter.values, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
    // filterKey names every filter.
  }, [startDate, endDate, filterKey, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityIncidents>(depth, path, setPath),
    ...metrics.map(([id, header, digits]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—',
      format: value => typeof value === 'number'
        ? value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }) : value,
    })),
  ]
  const range = `${startDate} to ${endDate}`
  const filtered = [...payerFilter.values.map(payer => payerLabels[payer] ?? payer), ...typeFilter.values,
    ...severityFilter.values.map(level => SEVERITY_LEVELS[level] ?? level)]
  const subtitle = `Resident incidents from ${range}${filtered.length ? `, filtered to ${filtered.join(', ')}` : ''}. Resulted in hospitalization counts the incidents that `
    + 'sent the resident to a hospital, each a hospital transfer for a fall or injury.'
    + ` Still open is the range's incidents whose investigation had not closed by ${data?.as_of
      ?? 'the latest day'}. Morning is 6:00 to 11:59, afternoon 12:00 to 17:59, evening 18:00 to 21:59, night 22:00 to 5:59. The rate is incidents per 1,000 resident days, each day's census summed over the range.`
  const file = `${startDate}-to-${endDate}`
  // The breakdowns follow the drilldown and custom grouping, as the table does:
  // the facilities shown, their counts added up, largest first.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  // Types read largest first; severity reads in level order, 1 to 5.
  const breakdown = (field: 'types' | 'severities', label: (key: string) => string) => {
    const totals = new Map<string, number>()
    for (const facility of scoped) {
      for (const [key, count] of Object.entries(facility[field])) totals.set(key, (totals.get(key) ?? 0) + count)
    }
    return [...totals].sort(([a, first], [b, second]) => field === 'severities' ? Number(a) - Number(b)
      : second - first || label(a).localeCompare(label(b))).map(([key, value]) => ({ label: label(key), value }))
  }
  const severityCode = (label: string) => Object.keys(SEVERITY_LEVELS).find(key => SEVERITY_LEVELS[key] === label) ?? label
  const status = { loading, error, onRetry }

  // The daily trend follows the same filters and the drilldown: every facility
  // at the top, the ones shown below it. Joined into a string so the fetch reruns
  // only when the facilities change; it waits for the table, which knows them.
  const scopedIds = (path.length || grouping ? scoped.map(facility => facility.facility_id) : []).join(',')
  const [daily, setDaily] = useState<DailyIncidents | null>(null)
  const [dailyError, setDailyError] = useState<string | null>(null)
  const [dailyRetry, setDailyRetry] = useState(0)
  useEffect(() => {
    if (!data) return
    const controller = new AbortController()
    setDailyError(null)
    getDailyIncidents(startDate, endDate, payerFilter.values, typeFilter.values, severityFilter.values,
      scopedIds ? scopedIds.split(',') : [], controller.signal)
      .then(body => { if (!controller.signal.aborted) setDaily(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setDailyError(failure.message) })
    return () => controller.abort()
    // filterKey and scopedIds name everything the request reads.
  }, [startDate, endDate, filterKey, scopedIds, Boolean(data), dailyRetry])
  // Long ranges are shown in equal blocks of days, as Daily Admissions is.
  const blockSize = trendBlockSize(startDate, endDate)
  const trend = groupTrendPeriods((daily?.days ?? []).map(day => ({ date: day.date, value: day.incidents })),
    startDate, blockSize)

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} incidents`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`incidents-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · Incidents, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`incidents-facilities-${file}.csv`} />
    {/* Each filters the report and keeps all of its own slices; the header has
        the same filters beside the date range. */}
    <div className="report-chart-grid">
      <DonutChart {...status} title="Incidents by type" valueLabel="Incidents"
        subtitle={`${scopeName} · Click incident types to filter the report`}
        items={breakdown('types', key => key)}
        selectedLabels={typeFilter.values} onClear={typeFilter.clear} onSelect={typeFilter.toggle}
        filterName={{ one: 'incident type', many: 'incident types' }} />
      <DonutChart {...status} title="Incidents by severity" valueLabel="Incidents"
        subtitle={`${scopeName} · Major and severe count as major · Click a severity to filter the report`}
        items={breakdown('severities', key => SEVERITY_LEVELS[key] ?? key)}
        selectedLabels={severityFilter.values.map(level => SEVERITY_LEVELS[level] ?? level)}
        onClear={severityFilter.clear} onSelect={label => severityFilter.toggle(severityCode(label))}
        filterName={{ one: 'severity', many: 'severities' }} />
    </div>
    <LineChart items={trend} title={blockSize === 1 ? 'Daily incidents' : 'Incidents trend'}
      // Red, the shared adverse colour: incidents are a count to bring down.
      valueLabel="Incidents" variant="bar" height={360} barColor="var(--color-table-change-adverse)"
      subtitle={`${scopeName} · ${blockSize === 1 ? 'Incidents each day'
        : `Incidents per ${blockSize}-day period; the tooltip shows the exact dates`}${filtered.length
        ? `, filtered to ${filtered.join(', ')}` : ''}.`}
      loading={loading || (!daily && !dailyError)} error={error ?? dailyError}
      onRetry={error ? onRetry : () => setDailyRetry(count => count + 1)} />
  </>
}
