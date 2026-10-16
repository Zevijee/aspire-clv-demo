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
import { useLocationSheets } from '../../../shared/locationSheets'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getMonthlyStaffing, STAFFING_ROLES, type MonthlyStaffing, type MonthlyStaffingFacility } from '../api'
import { formatMeasure as format } from '../laborCost'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { perRow } from '../perRow'

type Row = DrilldownRow<MonthlyStaffingFacility>
type MonthTotal = { month: string; value: number; hires: number }

/** A tab's dollar total by month: the labour cost, or the sign-on bonuses with
 * the new hires they were paid to. */
type Measure = {
  field: 'cost' | 'bonuses'
  name: string
  lower: string
  file: string
  explain: string
  /** The hires behind the total, shown beside it: the bonuses are paid per hire. */
  hires: boolean
}

const MEASURES: Record<'cost' | 'bonuses', Measure> = {
  cost: { field: 'cost', name: 'Total cost', lower: 'total cost', file: 'monthly-cost', hires: false,
    explain: 'Labour cost: straight-time pay, the agency premium, the overtime and holiday premiums, orientation and '
      + 'training pay, and bonuses, as the PPD cost report counts it' },
  bonuses: { field: 'bonuses', name: 'Bonuses', lower: 'bonuses', file: 'monthly-bonuses', hires: true,
    explain: 'Sign-on bonuses: what new hires were paid for joining, in the month they were hired, with the hires' },
}

const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')
const money = (value: number) => format(value, 'money') as string
// The axis short: a full dollar figure is wider than the axis and was cut off.
const axisMoney = (value: number) => Math.abs(value) >= 10_000_000 ? `$${(value / 1_000_000).toFixed(1)}M`
  : `$${Math.round(value / 1_000).toLocaleString()}K`

/** Each month's total over some facilities, and its new hires, summed; a month
 * with none is left out. */
function byMonth(measure: Measure, facilities: MonthlyStaffingFacility[], months: string[]): MonthTotal[] {
  return months.map(month => {
    let value = 0
    let hires = 0
    for (const facility of facilities) {
      value += facility[measure.field][month] ?? 0
      hires += facility.new_hires[month] ?? 0
    }
    return { month, value, hires }
  }).filter(month => month.value !== 0)
}

/** Monthly Staffing Trending's Cost and Bonuses tabs: for each location of the
 * drilldown, its total over the months picked, the average month, for bonuses
 * the hires they were paid to, and the months it was highest and lowest; then the
 * total month by month for the location shown. */
export function MonthlyStaffingTotal({ measure: measureId, initialPath }: { measure: 'cost' | 'bonuses'; initialPath?: string[] }) {
  const measure = MEASURES[measureId]
  const [params, setParams] = useReportSearchParams()
  const range = getReportMonthRange(params)
  const startMonth = range.start.format('YYYY-MM')
  const endMonth = range.end.format('YYYY-MM')
  // One drill= per level, in order; the Excel export's copy for a location starts there instead.
  const path = initialPath ?? params.getAll('drill')
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
  // The Excel export's sheet for each location in the table, this tab drilled into it.
  useLocationSheets(() => path.length === 4 ? [] : rows.map(row => ({ name: row.name,
    render: () => <MonthlyStaffingTotal measure={measureId} initialPath={row.path} /> })))
  // Each row's months and totals once, however many columns and sorts ask.
  const totals = perRow((row: Row) => byMonth(measure, row.facilities, monthKeys))
  const total = perRow((row: Row) => totals(row).reduce((sum, month) => sum + month.value, 0))
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => {
    const find = (row: Row) => totals(row).reduce<MonthTotal | null>((best, month) => !best
      || (pick === 'highest' ? month.value > best.value : month.value < best.value) ? month : best, null)
    return { id: pick, header: pick === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
      value: row => find(row)?.value ?? '—',
      format: (_, row) => {
        const found = find(row)
        return found ? `${monthLabel(found.month)} · ${money(found.value)}` : '—'
      } }
  }
  const columns: TableColumn<Row>[] = [
    locationColumn<MonthlyStaffingFacility>(depth, path, setPath),
    { id: 'total', header: measure.hires ? 'Total bonuses' : 'Total cost', numeric: true, value: total,
      format: value => format(value, 'money') },
    { id: 'average', header: `Avg. ${measure.hires ? 'bonuses' : 'cost'} per month`, numeric: true,
      value: row => totals(row).length ? total(row) / totals(row).length : '—', format: value => format(value, 'money') },
    ...(measure.hires ? [{ id: 'hires', header: 'New hires', numeric: true,
      value: (row: Row) => totals(row).reduce((sum, month) => sum + month.hires, 0),
      format: (value: number | string) => format(value, 'count') } as TableColumn<Row>] : []),
    extremeColumn('highest'),
    extremeColumn('lowest'),
  ]

  const partial = months.find(month => month.days < month.month_days)
  const span = data ? `${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}` : ''
  const subtitle = data ? `${measure.explain} -- ${roleName}, ${months.length} months, ${span}. The average is the total `
    + 'over the months; the highest and lowest months are the months it was most and least.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')}.` : '') : ''
  const file = `${startMonth}-to-${endMonth}`

  // The trend follows the drilldown: the facilities the table shows.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} ${measure.lower} by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`${measure.file}-${file}.csv`} />
    {/* The total moves a little on a large base, so the axis starts just below
        the lowest month rather than at zero. */}
    <LineChart title={`${measure.name} by month`} valueLabel={measure.name} variant="bar" interval="month" height={520}
      barColor="var(--color-chart-series-primary)" baseline="close" formatValue={money} formatAxis={axisMoney}
      subtitle={`${scopeName} · ${roleName} · Each month's ${measure.lower}${measure.hires ? ', with its new hires on hover'
        : ''}. The axis starts just below the lowest month, not at zero, so small differences show.`
        + (partial ? ` ${monthLabel(partial.month)} is month to date.` : '')}
      items={byMonth(measure, scoped, monthKeys).map(figure => {
        const month = months.find(entry => entry.month === figure.month)!
        return { date: `${figure.month}-01`,
          end_date: dayjs(`${figure.month}-01`).add(month.days - 1, 'day').format('YYYY-MM-DD'), value: figure.value,
          ...(measure.hires ? { details: [{ label: 'New hires', value: figure.hires.toLocaleString() }] } : {}) }
      })}
      loading={loading} error={error} onRetry={onRetry} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · ${measure.name} by month, ${roleName}, ${span}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`${measure.file}-facilities-${file}.csv`} />
  </>
}
