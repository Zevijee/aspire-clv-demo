import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { CensusPayerFilter } from './CensusPayerFilter'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getMonthlyCensus, type MonthlyCensusFacility, type MonthlyCensusReport } from '../api'

type Row = { key: string; name: string; path: string[]; facilities: MonthlyCensusFacility[]; isTotal?: boolean }
type Month = MonthlyCensusReport['months'][number]
type TrendRow = {
  month: string; start: string; end: string; days: number
  censusDays: number; average: number; opening: number; closing: number; occupancy: number
}
const levels = ['State', 'Portfolio', 'Region', 'Facility']
const location = (row: MonthlyCensusFacility) => [row.state, row.portfolio, row.region, row.facility_name]
const whole = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
const tenths = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')

/** One month's measure, summed over the row's facilities. */
const monthSum = (row: Row, month: string, measure: 'census_days' | 'opening_census' | 'closing_census') =>
  row.facilities.reduce((total, facility) => total + (facility[measure][month] ?? 0), 0)
const monthDays = (row: Row, month: string) => monthSum(row, month, 'census_days')

/** The month with the highest or lowest average daily census, after summing the
 * row's facilities. Ranked by average rather than census days, so February's
 * short month and the month in progress are not always lowest. */
function extreme(row: Row, months: Month[], pick: 'highest' | 'lowest') {
  let best: { month: string; average: number } | null = null
  for (const month of months) {
    const average = monthDays(row, month.month) / month.days
    if (!best || (pick === 'highest' ? average > best.average : average < best.average)) {
      best = { month: month.month, average }
    }
  }
  return best
}

/** Census by calendar month, drilled from state to facility. Census days sum;
 * everything else is divided once at the scope shown. */
export function MonthlyCensusTrending() {
  const [params] = useReportSearchParams()
  const range = getReportMonthRange(params)
  const startMonth = range.start.format('YYYY-MM')
  const endMonth = range.end.format('YYYY-MM')
  const payers = params.getAll('monthly_census_payer')
  const requestKey = JSON.stringify([startMonth, endMonth, payers])
  const [retry, setRetry] = useState(0)
  const [response, setResponse] = useState<{ key: string; data: MonthlyCensusReport } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [path, setPath] = useState<string[]>([])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const [showTrendTable, setShowTrendTable] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void getMonthlyCensus(startMonth, endMonth, (JSON.parse(requestKey) as [string, string, string[]])[2], controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startMonth, endMonth, requestKey, retry])

  const data = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const months = data?.months ?? []
  // A month in progress counts as the share of it covered, so the average per
  // month is per whole month.
  const monthEquivalents = months.reduce((total, month) => total + month.days / month.month_days, 0)
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

  const total = (row: Row) => months.reduce((sum, month) => sum + monthDays(row, month.month), 0)
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => ({
    id: pick, header: pick === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
    value: row => extreme(row, months, pick)?.average ?? 0,
    format: (_, row) => {
      const found = extreme(row, months, pick)
      return found ? `${monthLabel(found.month)} · ${tenths(found.average)}` : '—'
    },
  })
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    { id: 'census_days', header: 'Total census days', numeric: true, value: total,
      format: value => whole(Number(value)) },
    { id: 'per_month', header: 'Avg. census days per month', numeric: true,
      value: row => monthEquivalents > 0 ? total(row) / monthEquivalents : 0,
      format: value => whole(Number(value)) },
    extremeColumn('highest'),
    extremeColumn('lowest'),
  ]

  const partial = months.find(month => month.days < month.month_days)
  const subtitle = data ? `${months.length} months, ${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}. `
    + 'Census days sum every day\'s census. Highest and lowest months are ranked by average daily census, shown after the month.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')} and counts as part of a month.` : '')
    : ''
  // The trend follows the drilldown: every facility at the top, the ones under
  // the current path below it, summed before dividing by the month's days.
  const scope: Row = { key: 'scope', name: '', path, facilities: (data?.items ?? [])
    .filter(facility => path.every((value, index) => location(facility)[index] === value)) }
  const scopeName = path.length ? path[path.length - 1] : 'All locations'
  const scopeBeds = scope.facilities.reduce((total, facility) => total + facility.capacity, 0)
  const trendRows: TrendRow[] = months.map(month => {
    const censusDays = monthDays(scope, month.month)
    const average = censusDays / month.days
    return { month: month.month, start: `${month.month}-01`,
      end: dayjs(`${month.month}-01`).add(month.days - 1, 'day').format('YYYY-MM-DD'),
      days: month.days, censusDays, average,
      opening: monthSum(scope, month.month, 'opening_census'),
      closing: monthSum(scope, month.month, 'closing_census'),
      occupancy: scopeBeds > 0 ? average / scopeBeds * 100 : 0 }
  })
  const trendColumns: TableColumn<TrendRow>[] = [
    { id: 'month', header: 'Month', isRowHeader: true, value: row => row.month,
      format: (_, row) => monthLabel(row.month) },
    { id: 'census_days', header: 'Total census days', numeric: true, value: row => row.censusDays,
      format: value => whole(Number(value)) },
    { id: 'opening', header: 'Open census', numeric: true, value: row => row.opening, format: value => whole(Number(value)) },
    { id: 'closing', header: 'Close census', numeric: true, value: row => row.closing, format: value => whole(Number(value)) },
    { id: 'net_change', header: 'Net change', numeric: true, value: row => row.closing - row.opening,
      change: { favorable: 'increase' },
      format: value => Number(value).toLocaleString(undefined, { signDisplay: 'exceptZero' }) },
    { id: 'average', header: 'Avg. daily census', numeric: true, value: row => row.average,
      format: value => tenths(Number(value)) },
    { id: 'occupancy', header: 'Avg. daily occupancy', numeric: true, value: row => row.occupancy,
      format: value => `${tenths(Number(value))}%` },
  ]
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
    <DrilldownTable<Row> title={`${levels[depth]} monthly census`} columns={columns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-census-${startMonth}-to-${endMonth}.csv`} />
    {/* Census moves a few points on a base of a hundred or more, so bars from
        zero would all look the same height; the axis starts near the lowest month. */}
    <LineChart title="Monthly Census Trending" valueLabel="Avg. daily census" variant="bar" interval="month" height={400}
      barColor="var(--color-chart-series-primary)" baseline="fit"
      subtitle={`${scopeName}. Average daily census each month: its census days divided by its days. The axis starts near the lowest month, not at zero.${partial ? ` ${monthLabel(partial.month)} is month to date.` : ''}`}
      headerActions={<OpenViewButton kind="table" label="See in table view" onClick={() => setShowTrendTable(true)} />}
      items={trendRows.map(row => ({ date: row.start, end_date: row.end, value: Math.round(row.average * 10) / 10 }))}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)} />
    <FullScreenModal open={showTrendTable} onClose={() => setShowTrendTable(false)} destroyOnHidden
      title={`Monthly Census Trending · ${scopeName}, ${monthLabel(startMonth)} to ${monthLabel(endMonth)}`}>
      <div className="net-change-daily-modal__table">
        <Table<TrendRow> filters={<CensusPayerFilter param="monthly_census_payer" />} title="Monthly Census Trending"
          subtitle="Each month's census days, its open and close census, and its average daily census and occupancy. The month in progress closes on the latest day."
          columns={trendColumns} rows={trendRows} getRowKey={row => row.month}
          initialSort={{ columnId: 'month', direction: 'descending' }} internalScroll stickyFirstColumn
          loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
          emptyMessage="No months in this range."
          csvFileName={`monthly-census-trend-${startMonth}-to-${endMonth}.csv`} />
      </div>
    </FullScreenModal>
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      filters={<CensusPayerFilter param="monthly_census_payer" />}
      title={`All facilities · ${monthLabel(startMonth)} to ${monthLabel(endMonth)}`} subtitle={subtitle}
      rows={facilityRows} columns={columns.slice(1)} getRowKey={row => row.key} getName={row => row.name}
      getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      csvFileName={`monthly-census-facilities-${startMonth}-to-${endMonth}.csv`} />
  </>
}
