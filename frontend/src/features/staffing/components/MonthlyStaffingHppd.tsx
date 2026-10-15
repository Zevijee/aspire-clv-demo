import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LineChart } from '../../../shared/components/charts/LineChart'
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
type Sums = { hours: number; target: number; cost: number; censusDays: number }
type MonthFigure = { month: string; hppd: number; budget: number; variance: number; ppdCost: number }

const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')
const hppd = (value: number) => value.toFixed(2)

/** Hours, budget hours, labour cost and census days over some facilities and
 * months, summed before anything is divided. */
function sum(facilities: MonthlyStaffingFacility[], months: string[]): Sums {
  const sums: Sums = { hours: 0, target: 0, cost: 0, censusDays: 0 }
  for (const facility of facilities) {
    for (const month of months) {
      sums.hours += facility.hours[month] ?? 0
      sums.target += facility.target_hours[month] ?? 0
      sums.cost += facility.cost[month] ?? 0
      sums.censusDays += facility.census_days[month] ?? 0
    }
  }
  return sums
}

/** Each month's HPPD against its budget over some facilities, each month summed
 * and divided once; a month with no census is left out. */
function byMonth(facilities: MonthlyStaffingFacility[], months: string[]): MonthFigure[] {
  return months.flatMap(month => {
    const sums = sum(facilities, [month])
    if (sums.censusDays <= 0) return []
    const value = sums.hours / sums.censusDays
    const budget = sums.target / sums.censusDays
    return [{ month, hppd: value, budget, variance: value - budget, ppdCost: sums.cost / sums.censusDays }]
  })
}

/** The month furthest over budget, or furthest under it. */
function extreme(figures: MonthFigure[], pick: 'highest' | 'lowest') {
  return figures.reduce<MonthFigure | null>((best, figure) => !best
    || (pick === 'highest' ? figure.variance > best.variance : figure.variance < best.variance) ? figure : best, null)
}

/** Monthly Staffing Trending's HPPD/PPD tab: for each location of the drilldown,
 * how many months of those picked its HPPD was over its budget and how many
 * under, the month most over and the month most under, and its HPPD against
 * budget over all of them; then the HPPD of the location shown month by month,
 * with its PPD cost on hover. Every month is summed over its facilities and roles
 * first and divided once. */
export function MonthlyStaffingHppd() {
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
  const monthKeys = months.map(month => month.month)
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // Each row's months and sums once, however many columns and sorts ask.
  const figures = perRow((row: Row) => byMonth(row.facilities, monthKeys))
  const totals = perRow((row: Row) => sum(row.facilities, monthKeys))
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => ({
    id: pick, header: pick === 'highest' ? 'Highest variance' : 'Lowest variance', numeric: true,
    value: row => extreme(figures(row), pick)?.variance ?? '—',
    format: (_, row) => {
      const found = extreme(figures(row), pick)
      return found ? `${monthLabel(found.month)} · ${format(found.variance, 'variance')}` : '—'
    },
  })
  const columns: TableColumn<Row>[] = [
    locationColumn<MonthlyStaffingFacility>(depth, path, setPath),
    { id: 'over', header: 'Months over budget', numeric: true,
      value: row => figures(row).filter(figure => figure.variance > 0).length },
    { id: 'under', header: 'Months under budget', numeric: true,
      value: row => figures(row).filter(figure => figure.variance < 0).length },
    extremeColumn('highest'),
    extremeColumn('lowest'),
    { id: 'average', header: 'Avg. variance', numeric: true, change: { favorable: 'neutral' },
      value: row => {
        const sums = totals(row)
        return sums.censusDays > 0 ? (sums.hours - sums.target) / sums.censusDays : '—'
      },
      format: value => format(value, 'variance') },
  ]

  const partial = months.find(month => month.days < month.month_days)
  const span = data ? `${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}` : ''
  const subtitle = data ? `HPPD against budget, ${roleName}, ${months.length} months, ${span}. Each month's HPPD is `
    + 'its hours worked over its census days, and its budget the target hours over the same days; a month is over '
    + 'or under budget by the difference, its variance. The highest and lowest variance are the months most over and '
    + 'most under budget. The average variance is over every month together: all their hours against all their '
    + 'budget, over all their census days.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')}.` : '') : ''
  const file = `${startMonth}-to-${endMonth}`

  // The trend follows the drilldown: the facilities the table shows.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const whole = sum(scoped, monthKeys)
  const budget = whole.censusDays > 0 ? whole.target / whole.censusDays : null

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} HPPD by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-hppd-${file}.csv`} />
    {/* HPPD moves a few hundredths on a base of six, so bars from zero, or from
        a whole number below, would all look the same height; the axis starts
        just below the lowest month or the budget. */}
    <LineChart title="HPPD by month" valueLabel="HPPD" variant="bar" interval="month" height={520}
      barColor="var(--color-chart-series-primary)" baseline="close" formatValue={hppd}
      // Ticks fall hundredths apart; a decimal finer, so neighbours never read the same.
      formatAxis={value => value.toFixed(3)}
      referenceLines={budget === null ? [] : [{ value: budget, label: `Budget ${hppd(budget)}` }]}
      subtitle={`${scopeName} · ${roleName} · Each month's HPPD, with its PPD cost on hover. The dashed line is the `
        + 'budget HPPD over the months shown. The axis starts just below the lowest month, not at zero, so small '
        + 'differences show.'
        + (partial ? ` ${monthLabel(partial.month)} is month to date.` : '')}
      items={byMonth(scoped, monthKeys).map(figure => {
        const month = months.find(entry => entry.month === figure.month)!
        return { date: `${figure.month}-01`,
          end_date: dayjs(`${figure.month}-01`).add(month.days - 1, 'day').format('YYYY-MM-DD'),
          // Not rounded: the months differ by hundredths, and rounded they only
          // ever stepped between a few heights.
          value: figure.hppd,
          // The month's labour cost over its census days, as the PPD cost report counts it.
          details: [{ label: 'PPD cost', value: format(figure.ppdCost, 'rate') as string }] }
      })}
      loading={loading} error={error} onRetry={onRetry} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · HPPD by month, ${roleName}, ${span}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`monthly-hppd-facilities-${file}.csv`} />
  </>
}
