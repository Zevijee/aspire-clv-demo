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
type Premiums = { excess: number; agency: number; overtime: number; total: number }
type MonthPremiums = Premiums & { month: string }

// The premiums and extras, as the Premiums and extras report names them.
const PARTS: [key: keyof Omit<Premiums, 'total'>, label: string, field: keyof MonthlyStaffingFacility][] = [
  ['excess', 'Overbudget excess spend', 'excess_wages'],
  ['agency', 'Agency premium', 'agency_premium'],
  ['overtime', 'Overtime premium', 'overtime_premium'],
]

const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')
const money = (value: number) => format(value, 'money') as string
// The axis in millions: a full dollar figure is wider than the axis and was cut off.
const millions = (value: number) => `$${(value / 1_000_000).toFixed(2)}M`

/** Each premium and their total over some facilities and months, summed. */
function sum(facilities: MonthlyStaffingFacility[], months: string[]): Premiums {
  const sums: Premiums = { excess: 0, agency: 0, overtime: 0, total: 0 }
  for (const facility of facilities) {
    for (const month of months) {
      for (const [key, , field] of PARTS) {
        const value = (facility[field] as Record<string, number>)[month] ?? 0
        sums[key] += value
        sums.total += value
      }
    }
  }
  return sums
}

const byMonth = (facilities: MonthlyStaffingFacility[], months: string[]): MonthPremiums[] =>
  months.map(month => ({ month, ...sum(facilities, [month]) })).filter(month => month.total !== 0)

/** Monthly Staffing Trending's Premiums and extras tab: for each location of the
 * drilldown, what it paid over budget and over straight time across the months
 * picked -- overbudget excess spend, the agency premium and the overtime premium,
 * as the Premiums and extras report counts them -- their total, and the months
 * the total was highest and lowest; then the total month by month for the
 * location shown, each premium on hover. */
export function MonthlyStaffingPremiums({ initialPath }: { initialPath?: string[] } = {}) {
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
    render: () => <MonthlyStaffingPremiums initialPath={row.path} /> })))
  // Each row's months and sums once, however many columns and sorts ask.
  const premiums = perRow((row: Row) => byMonth(row.facilities, monthKeys))
  const totals = perRow((row: Row) => sum(row.facilities, monthKeys))
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => {
    const find = (row: Row) => premiums(row).reduce<MonthPremiums | null>((best, month) => !best
      || (pick === 'highest' ? month.total > best.total : month.total < best.total) ? month : best, null)
    return { id: pick, header: pick === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
      value: row => find(row)?.total ?? '—',
      format: (_, row) => {
        const found = find(row)
        return found ? `${monthLabel(found.month)} · ${money(found.total)}` : '—'
      } }
  }
  const columns: TableColumn<Row>[] = [
    locationColumn<MonthlyStaffingFacility>(depth, path, setPath),
    ...PARTS.map(([key, label]): TableColumn<Row> => ({ id: key, header: label, numeric: true,
      value: row => totals(row)[key], format: value => format(value, 'money') })),
    { id: 'total', header: 'Total premiums', numeric: true, value: row => totals(row).total,
      format: value => format(value, 'money') },
    extremeColumn('highest'),
    extremeColumn('lowest'),
  ]

  const partial = months.find(month => month.days < month.month_days)
  const span = data ? `${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}` : ''
  const subtitle = data ? `What was paid over budget and over straight time, ${roleName}, ${months.length} months, `
    + `${span}. Overbudget excess spend is the hours over each day's budget at straight time; the agency premium what `
    + 'agency hours cost over the in-house rate; and the overtime premium what overtime hours paid over straight time. '
    + 'Total premiums adds them up. The highest and lowest months are the months the total was highest and lowest.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')}.` : '') : ''
  const file = `${startMonth}-to-${endMonth}`

  // The trend follows the drilldown: the facilities the table shows.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} premiums and extras by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-premiums-${file}.csv`} />
    {/* Only the total is drawn; each premium is on hover. The total moves a
        little on a large base, so the axis starts just below the lowest month. */}
    <LineChart title="Total premiums by month" valueLabel="Total premiums" variant="bar" interval="month"
      height={520} barColor="var(--color-chart-series-primary)" baseline="close" formatValue={money} formatAxis={millions}
      subtitle={`${scopeName} · ${roleName} · Each month's premiums and extras added up, each one on hover. The axis `
        + 'starts just below the lowest month, not at zero, so small differences show.'
        + (partial ? ` ${monthLabel(partial.month)} is month to date.` : '')}
      items={byMonth(scoped, monthKeys).map(figure => {
        const month = months.find(entry => entry.month === figure.month)!
        return { date: `${figure.month}-01`,
          end_date: dayjs(`${figure.month}-01`).add(month.days - 1, 'day').format('YYYY-MM-DD'),
          value: figure.total,
          details: PARTS.map(([key, label]) => ({ label, value: money(figure[key]) })) }
      })}
      loading={loading} error={error} onRetry={onRetry} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · Premiums and extras by month, ${roleName}, ${span}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`monthly-premiums-facilities-${file}.csv`} />
  </>
}
