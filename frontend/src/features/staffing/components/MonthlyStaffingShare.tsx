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
type MonthShare = { month: string; part: number; hours: number; share: number }

/** A kind of hour shown as its share of the hours worked: agency's, or overtime's. */
type Kind = {
  field: 'agency_hours' | 'overtime_hours'
  name: string
  lower: string
  hours: string
  file: string
  explain: string
}

const KINDS: Record<'agency' | 'overtime', Kind> = {
  agency: { field: 'agency_hours', name: 'Agency share', lower: 'agency share', hours: 'Agency hours',
    file: 'monthly-agency', explain: "Agency's share of the hours worked -- the hours agency employees worked over "
      + "everyone's" },
  overtime: { field: 'overtime_hours', name: 'Overtime share', lower: 'overtime share', hours: 'Overtime hours',
    file: 'monthly-overtime', explain: "Overtime's share of the hours worked -- the hours over 40 in an employee's "
      + 'week over all the hours worked' },
}

const monthLabel = (month: string) => dayjs(`${month}-01`).format('MMM YYYY')
const percent = (value: number) => `${value.toFixed(2)}%`
// The axis a decimal finer: its ticks fall hundredths of a point apart, and at
// two decimals neighbours read the same.
const axisPercent = (value: number) => `${value.toFixed(3)}%`

/** The kind's hours and all hours worked over some facilities and months, summed first. */
function sum(kind: Kind, facilities: MonthlyStaffingFacility[], months: string[]) {
  let part = 0
  let hours = 0
  for (const facility of facilities) {
    for (const month of months) {
      part += facility[kind.field][month] ?? 0
      hours += facility.hours[month] ?? 0
    }
  }
  return { part, hours }
}

/** Each month's share over some facilities, as a percentage, each month summed
 * and divided once; a month with no hours is left out. */
function byMonth(kind: Kind, facilities: MonthlyStaffingFacility[], months: string[]): MonthShare[] {
  return months.flatMap(month => {
    const { part, hours } = sum(kind, facilities, [month])
    return hours > 0 ? [{ month, part, hours, share: part / hours * 100 }] : []
  })
}

/** Monthly Staffing Trending's Agency vs In-house and Overtime tabs: for each
 * location of the drilldown, the share of its hours worked that were agency's, or
 * overtime, over the months picked, those hours and all its hours, and the months
 * the share was highest and lowest; then the share month by month for the
 * location shown. Every share is the hours over the hours worked, each summed first. */
export function MonthlyStaffingShare({ kind: kindId, initialPath }: { kind: 'agency' | 'overtime'; initialPath?: string[] }) {
  const kind = KINDS[kindId]
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
    render: () => <MonthlyStaffingShare kind={kindId} initialPath={row.path} /> })))
  // Each row's months and sums once, however many columns and sorts ask.
  const shares = perRow((row: Row) => byMonth(kind, row.facilities, monthKeys))
  const totals = perRow((row: Row) => sum(kind, row.facilities, monthKeys))
  const extremeColumn = (pick: 'highest' | 'lowest'): TableColumn<Row> => {
    const find = (row: Row) => shares(row).reduce<MonthShare | null>((best, month) => !best
      || (pick === 'highest' ? month.share > best.share : month.share < best.share) ? month : best, null)
    return { id: pick, header: pick === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
      value: row => find(row)?.share ?? '—',
      format: (_, row) => {
        const found = find(row)
        return found ? `${monthLabel(found.month)} · ${percent(found.share)}` : '—'
      } }
  }
  const columns: TableColumn<Row>[] = [
    locationColumn<MonthlyStaffingFacility>(depth, path, setPath),
    { id: 'share', header: kind.name, numeric: true,
      value: row => {
        const { part, hours } = totals(row)
        return hours > 0 ? part / hours * 100 : '—'
      },
      format: value => typeof value === 'number' ? percent(value) : value },
    { id: 'part', header: kind.hours, numeric: true, value: row => totals(row).part,
      format: value => format(value, 'hours') },
    { id: 'hours', header: 'Hours worked', numeric: true, value: row => totals(row).hours,
      format: value => format(value, 'hours') },
    extremeColumn('highest'),
    extremeColumn('lowest'),
  ]

  const partial = months.find(month => month.days < month.month_days)
  const span = data ? `${monthLabel(months[0].month)} to ${monthLabel(months.at(-1)!.month)}` : ''
  const subtitle = data ? `${kind.explain} -- ${roleName}, ${months.length} months, ${span}, over all the months `
    + 'together. The highest and lowest months are the months its share was highest and lowest.'
    + (partial ? ` ${monthLabel(partial.month)} runs through ${dayjs(data.end).format('MMM D')}.` : '') : ''
  const file = `${startMonth}-to-${endMonth}`

  // The trend follows the drilldown: the facilities the table shows.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} ${kind.lower} by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`${kind.file}-${file}.csv`} />
    {/* The share moves a point or two on a base of a few, so the axis starts
        just below the lowest month rather than at zero. */}
    <LineChart title={`${kind.name} of hours by month`} valueLabel={kind.name} variant="bar" interval="month"
      height={520} barColor="var(--color-chart-series-primary)" baseline="close" formatValue={percent} formatAxis={axisPercent}
      subtitle={`${scopeName} · ${roleName} · Each month's ${kind.hours.toLowerCase()} as a share of all the hours worked, with both `
        + 'on hover. The axis starts just below the lowest month, not at zero, so small differences show.'
        + (partial ? ` ${monthLabel(partial.month)} is month to date.` : '')}
      items={byMonth(kind, scoped, monthKeys).map(figure => {
        const month = months.find(entry => entry.month === figure.month)!
        return { date: `${figure.month}-01`,
          end_date: dayjs(`${figure.month}-01`).add(month.days - 1, 'day').format('YYYY-MM-DD'),
          // Not rounded: the months differ by hundredths of a point, and rounded
          // they only ever stepped between two or three heights.
          value: figure.share,
          details: [{ label: kind.hours, value: format(figure.part, 'hours') as string },
            { label: 'Hours worked', value: format(figure.hours, 'hours') as string }] }
      })}
      loading={loading} error={error} onRetry={onRetry} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · ${kind.name} by month, ${roleName}, ${span}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`${kind.file}-facilities-${file}.csv`} />
  </>
}
