import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { GainLossChart } from '../../../shared/components/charts/GainLossChart'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getMonthlyStaffing, STAFFING_ROLES, type MonthlyStaffing, type MonthlyStaffingFacility } from '../api'
import { formatMeasure as format } from '../laborCost'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { perRow } from '../perRow'

type Row = DrilldownRow<MonthlyStaffingFacility>
type Month = MonthlyStaffing['months'][number]
type MonthTurnover = { month: string; days: number; start: number; end: number; hires: number; departures: number
  retained: number; turnover: number | null }

const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')
const percent = (value: number) => `${value.toFixed(1)}%`

/** Each month's counts over some facilities, summed, and its turnover:
 * departures over the average of its start and end headcount, scaled to a year
 * from the month's days. */
function byMonth(facilities: MonthlyStaffingFacility[], months: Month[]): MonthTurnover[] {
  return months.map(({ month, days }) => {
    const total = (field: 'headcount_start' | 'headcount_end' | 'hires' | 'departures' | 'retained') =>
      facilities.reduce((sum, facility) => sum + (facility[field][month] ?? 0), 0)
    const start = total('headcount_start')
    const end = total('headcount_end')
    const departures = total('departures')
    const average = (start + end) / 2
    return { month, days, start, end, hires: total('hires'), departures, retained: total('retained'),
      turnover: average > 0 && days > 0 ? departures / average * (365 / days) * 100 : null }
  })
}

/** The months together: the headcount at the first month's start and the last's
 * end, every hire and departure, and turnover over the average headcount, scaled
 * to a year from every day covered. */
function overall(figures: MonthTurnover[]) {
  const start = figures[0]?.start ?? 0
  const end = figures.at(-1)?.end ?? 0
  const days = figures.reduce((sum, month) => sum + month.days, 0)
  const departures = figures.reduce((sum, month) => sum + month.departures, 0)
  const average = (start + end) / 2
  return { average, departures, hires: figures.reduce((sum, month) => sum + month.hires, 0),
    turnover: average > 0 && days > 0 ? departures / average * (365 / days) * 100 : null }
}

/** Monthly Staffing Trending's Turnover and Retention tab: for each location of
 * the drilldown, its own employees over the months picked -- the average
 * headcount, hires and departures, turnover scaled to a year, and the months it
 * was highest and lowest; then each month's hires above a line and departures
 * below it for the location shown, with its turnover, headcount and retention on
 * hover. From the
 * roster, as Turnover and Retention counts it; agency staff are not counted. */
export function MonthlyStaffingTurnover() {
  const [params, setParams] = useReportSearchParams()
  const range = getReportMonthRange(params)
  const startMonth = range.start.format('YYYY-MM')
  const endMonth = range.end.format('YYYY-MM')
  // One drill= per level, in order.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(level => updated.append('drill', level))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const { roles, roleName, filter: roleFilter } = useDrilldownRoles()
  // Every role is asked for as none, the server's default.
  const asked = roles.length === STAFFING_ROLES.length ? [] : roles
  const requestKey = JSON.stringify([startMonth, endMonth, asked])
  const [response, setResponse] = useState<{ key: string; data: MonthlyStaffing } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    const [start, end, picked] = JSON.parse(requestKey) as [string, string, string[]]
    // Shared between the tabs (getMonthlyStaffing): leaving ignores the answer, never cancels it.
    getMonthlyStaffing(start, end, picked)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message }) })
    return () => controller.abort()
  }, [requestKey, retry])
  const data = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const loading = !data && !error
  const onRetry = () => setRetry(count => count + 1)

  const months = data?.months ?? []
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // Each row's months and totals once, however many columns and sorts ask.
  const figures = perRow((row: Row) => byMonth(row.facilities, months))
  const totals = perRow((row: Row) => overall(figures(row)))
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => {
    const find = (row: Row) => figures(row).filter(month => month.turnover !== null).reduce<MonthTurnover | null>(
      (best, month) => !best || (pick === 'highest' ? month.turnover! > best.turnover! : month.turnover! < best.turnover!)
        ? month : best, null)
    return { id: pick, header: pick === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
      value: row => find(row)?.turnover ?? '—',
      format: (_, row) => {
        const found = find(row)
        return found ? `${monthLabel(found.month)} · ${percent(found.turnover!)}` : '—'
      } }
  }
  const columns: TableColumn<Row>[] = [
    locationColumn<MonthlyStaffingFacility>(depth, path, setPath),
    { id: 'headcount', header: 'Avg. headcount', numeric: true, value: row => totals(row).average,
      format: value => format(value, 'count') },
    { id: 'hires', header: 'Hires', numeric: true, value: row => totals(row).hires, format: value => format(value, 'count') },
    { id: 'departures', header: 'Departures', numeric: true, value: row => totals(row).departures,
      format: value => format(value, 'count') },
    { id: 'turnover', header: 'Turnover (annualized)', numeric: true, value: row => totals(row).turnover ?? '—',
      format: value => typeof value === 'number' ? percent(value) : value },
    extremeColumn('highest'),
    extremeColumn('lowest'),
  ]

  const partial = months.find(month => month.days < month.month_days)
  const span = data ? `${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}` : ''
  const subtitle = data ? `The facilities' own employees, ${roleName}, ${months.length} months, ${span}; agency staff `
    + 'are not counted. Average headcount is the mean of the headcount at the first month\'s start and the last\'s '
    + 'end; turnover the departures over it, scaled to a year. The highest and lowest months are the months turnover '
    + 'was highest and lowest.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')}.` : '') : ''
  const file = `${startMonth}-to-${endMonth}`

  // The trend follows the drilldown: the facilities the table shows.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} turnover by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-turnover-${file}.csv`} />
    {/* Hires above the line and departures below it, each month: what came in and
        what went out, not only what it came to. */}
    <GainLossChart title="Hires and departures by month" gainLabel="Hires" lossLabel="Departures" height={520}
      subtitle={`${scopeName} · ${roleName} · Each month's hires above the line and departures below it, with its `
        + 'turnover, headcount and retention on hover.' + (partial ? ` ${monthLabel(partial.month)} is month to date.` : '')}
      items={byMonth(scoped, months).map(figure => ({
        date: `${figure.month}-01`,
        end_date: dayjs(`${figure.month}-01`).add(figure.days - 1, 'day').format('YYYY-MM-DD'),
        gain: figure.hires,
        loss: figure.departures,
        details: [
          { label: 'Turnover (annualized)', value: figure.turnover === null ? '—' : percent(figure.turnover) },
          { label: 'Headcount at month end', value: figure.end.toLocaleString() },
          // Of those employed at the month's start, the share still there at its end.
          { label: 'Retention', value: figure.start > 0 ? percent(figure.retained / figure.start * 100) : '—' },
        ] }))}
      loading={loading} error={error} onRetry={onRetry} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · Turnover by month, ${roleName}, ${span}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`monthly-turnover-facilities-${file}.csv`} />
  </>
}
