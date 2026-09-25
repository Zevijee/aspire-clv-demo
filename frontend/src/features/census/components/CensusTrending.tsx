import { useEffect, useState } from 'react'
import { CensusPayerFilter } from './CensusPayerFilter'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import type { TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { Table } from '../../../shared/components/Table'
import {
  getCensusTrending, getCensusTrendingDaily,
  type CensusDailyTrend, type CensusTrendingReport, type FacilityTrend,
} from '../api'

type Row = { key: string; name: string; path: string[]; facilities: FacilityTrend[]; isTotal?: boolean }
type TrendRow = { date: string; census: number; opening: number }
type Summed = 'census_days' | 'capacity' | 'opening_census' | 'closing_census'
const levels = ['State', 'Portfolio', 'Region', 'Facility']
const location = (row: FacilityTrend) => [row.state, row.portfolio, row.region, row.facility_name]
const sum = (row: Row, field: Summed) => row.facilities.reduce((total, facility) => total + facility[field], 0)

/** Census over the selected range, drilled from state to facility. Every
 * measure is summed at the scope shown and divided once -- never an average of
 * facility averages. */
export function CensusTrending() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // Payer types from the header filter; census narrows to them, and occupancy
  // becomes their share of beds.
  const payers = params.getAll('trending_payer')
  const requestKey = JSON.stringify([startDate, endDate, payers])
  const [retry, setRetry] = useState(0)
  const [response, setResponse] = useState<{ key: string; data: CensusTrendingReport } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [path, setPath] = useState<string[]>([])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const [showTrendTable, setShowTrendTable] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void getCensusTrending(startDate, endDate, (JSON.parse(requestKey) as [string, string, string[]])[2], controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, requestKey, retry])

  const data = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const days = data?.range.days ?? 1
  const depth = Math.min(path.length, 3)
  const groups = new Map<string, Row>()
  for (const facility of data?.items ?? []) {
    const parts = location(facility)
    if (!path.every((value, index) => parts[index] === value)) continue
    const nextPath = parts.slice(0, depth + 1)
    const key = JSON.stringify(nextPath)
    const row = groups.get(key) ?? { key, name: parts[depth], path: nextPath, facilities: [] }
    row.facilities.push(facility)
    groups.set(key, row)
  }

  const whole = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const tenths = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    { id: 'census_days', header: 'Total census days', numeric: true, value: row => sum(row, 'census_days'),
      format: value => whole(Number(value)) },
    { id: 'average', header: 'Avg. daily census', numeric: true, value: row => sum(row, 'census_days') / days,
      format: value => tenths(Number(value)) },
    { id: 'occupancy', header: 'Avg. daily occupancy', numeric: true,
      value: row => { const beds = sum(row, 'capacity'); return beds > 0 ? sum(row, 'census_days') / days / beds * 100 : 0 },
      format: value => `${tenths(Number(value))}%` },
    { id: 'opening', header: 'Open census', numeric: true, value: row => sum(row, 'opening_census'),
      format: value => whole(Number(value)) },
    { id: 'closing', header: 'Close census', numeric: true, value: row => sum(row, 'closing_census'),
      format: value => whole(Number(value)) },
    { id: 'net_change', header: 'Net change', numeric: true,
      value: row => sum(row, 'closing_census') - sum(row, 'opening_census'),
      change: { favorable: 'increase' },
      format: value => Number(value).toLocaleString(undefined, { signDisplay: 'exceptZero' }) },
  ]

  const subtitle = data ? `${data.range.days} days. Census days sum every day's census; the averages divide them by `
    + 'the days in the range, and occupancy by beds as well. Open census is the start of the first day, close '
    + 'census the end of the last.' : ''
  // The trend follows the drilldown: every facility at the top, the ones under
  // the current path below it. Empty means all, so the top needs no id list.
  const scopedIds = path.length ? (data?.items ?? [])
    .filter(facility => path.every((value, index) => location(facility)[index] === value))
    .map(facility => facility.facility_id) : []
  const trendKey = JSON.stringify([startDate, endDate, scopedIds, retry, payers])
  const [trend, setTrend] = useState<{ key: string; data?: CensusDailyTrend; error?: string } | null>(null)
  useEffect(() => {
    if (!data) return
    const controller = new AbortController()
    // Read back from the key, so the effect depends on a string, not a new array each render.
    const [, , ids, , payerTypes] = JSON.parse(trendKey) as [string, string, string[], number, string[]]
    void getCensusTrendingDaily(startDate, endDate, payerTypes, ids, controller.signal)
      .then(result => { if (!controller.signal.aborted) setTrend({ key: trendKey, data: result }) },
        (failure: Error) => { if (!controller.signal.aborted) setTrend({ key: trendKey, error: failure.message }) })
    return () => controller.abort()
  }, [data, startDate, endDate, trendKey])
  const currentTrend = trend?.key === trendKey ? trend : null
  const trendDays = currentTrend?.data?.days ?? []
  const trendRows: TrendRow[] = trendDays.map(day => ({ date: day.date, census: day.census, opening: day.opening_census }))
  // Beds of the facilities the chart covers, for each day's occupancy.
  const scopeBeds = (data?.items ?? [])
    .filter(facility => path.every((value, index) => location(facility)[index] === value))
    .reduce((total, facility) => total + facility.capacity, 0)
  const dayFormat = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
  const trendColumns: TableColumn<TrendRow>[] = [
    { id: 'date', header: 'Date', isRowHeader: true, value: row => row.date,
      format: (_, row) => dayFormat.format(new Date(`${row.date}T00:00:00Z`)) },
    // The drilldown's columns, for one day each: census days and the average are
    // that day's census.
    { id: 'census_days', header: 'Total census days', numeric: true, value: row => row.census,
      format: value => whole(Number(value)) },
    { id: 'average', header: 'Avg. daily census', numeric: true, value: row => row.census,
      format: value => tenths(Number(value)) },
    { id: 'occupancy', header: 'Avg. daily occupancy', numeric: true,
      value: row => scopeBeds > 0 ? row.census / scopeBeds * 100 : 0, format: value => `${tenths(Number(value))}%` },
    { id: 'opening', header: 'Open census', numeric: true, value: row => row.opening, format: value => whole(Number(value)) },
    { id: 'closing', header: 'Close census', numeric: true, value: row => row.census, format: value => whole(Number(value)) },
    { id: 'net_change', header: 'Net change', numeric: true, value: row => row.census - row.opening,
      change: { favorable: 'increase' },
      format: value => Number(value).toLocaleString(undefined, { signDisplay: 'exceptZero' }) },
  ]
  const scopeName = path.length ? path[path.length - 1] : 'All locations'

  const facilityRows: Row[] = (data?.items ?? []).map(facility => ({
    key: facility.facility_id, name: facility.facility_name, path: location(facility), facilities: [facility] }))

  return <>
    <DrilldownNavigation locationView={{
      groupBy: 'state', selectedCount: 0,
      onReturn: () => setPath([]),
      onClear: () => setPath([]),
    }} items={path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
      onSelect: () => setPath(path.slice(0, index + 1)) }))}
      level={{ current: depth + 1, total: 4, label: levels[depth] }} />
    <DrilldownTable<Row> title={`${levels[depth]} census`} columns={columns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`census-trending-${startDate}-to-${endDate}.csv`} />
    <LineChart title="Daily Census Trending" valueLabel="Census" variant="line" height={360}
      subtitle={`${scopeName}. Census at the close of each day.`}
      headerActions={<OpenViewButton kind="table" label="See in table view" onClick={() => setShowTrendTable(true)} />}
      items={(currentTrend?.data?.days ?? []).map(day => ({ date: day.date, value: day.census }))}
      loading={!error && (!data || currentTrend === null)} error={error ?? currentTrend?.error}
      onRetry={() => setRetry(value => value + 1)} />
    <FullScreenModal open={showTrendTable} onClose={() => setShowTrendTable(false)} destroyOnHidden
      title={`Daily Census Trending · ${scopeName}, ${startDate} to ${endDate}`}>
      <div className="net-change-daily-modal__table">
        <Table<TrendRow> filters={<CensusPayerFilter param="trending_payer" />} title="Daily Census Trending" subtitle="Each day's census, occupancy, and net change from its open to its close."
          columns={trendColumns} rows={trendRows} getRowKey={row => row.date}
          initialSort={{ columnId: 'date', direction: 'ascending' }} internalScroll stickyFirstColumn
          loading={!error && (!data || currentTrend === null)} error={error ?? currentTrend?.error}
          onRetry={() => setRetry(value => value + 1)} emptyMessage="No days in this range."
          csvFileName={`daily-census-${startDate}-to-${endDate}.csv`} />
      </div>
    </FullScreenModal>
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      filters={<CensusPayerFilter param="trending_payer" />}
      title={`All facilities · ${startDate} to ${endDate}`} subtitle={subtitle}
      rows={facilityRows} columns={columns.slice(1)} getRowKey={row => row.key} getName={row => row.name}
      getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      csvFileName={`census-trending-facilities-${startDate}-to-${endDate}.csv`} />
  </>
}
