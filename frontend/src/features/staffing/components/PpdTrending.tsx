import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useLocationSheets } from '../../../shared/locationSheets'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getPpdTrend, TREND_ROLE_PARAM, type FacilityTrend, type PpdTrend } from '../api'
import { useStaffingRoles } from './StaffingRolePicker'

type Row = DrilldownRow<FacilityTrend>
// How far from target counts as overstaffed or understaffed on the chart: a
// demo rule, 5% either side, not a regulatory line.
const STAFFING_BAND = 0.05
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const ppdFormat = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** The scope's series: the facilities' hours, targets and census added up
 * day by day, so any day's HPPD is the scope's hours over its census. */
function series(row: Row, days: number) {
  const hours = new Array<number>(days).fill(0)
  const targets = new Array<number>(days).fill(0)
  const census = new Array<number>(days).fill(0)
  for (const facility of row.facilities) {
    for (let index = 0; index < days; index++) {
      hours[index] += facility.hours[index] ?? 0
      targets[index] += facility.target_hours[index] ?? 0
      census[index] += facility.census[index] ?? 0
    }
  }
  return { hours, targets, census }
}

const ratio = (numerator: number, denominator: number) => denominator > 0 ? numerator / denominator : null
const sum = (values: number[], from = 0, to = values.length) => {
  let total = 0
  for (let index = from; index < to; index++) total += values[index]
  return total
}

/** The trend's figures at one scope, each a sum divided once: never an
 * average of facility HPPDs. */
function stats(row: Row, dates: string[]) {
  const days = dates.length
  const { hours, targets, census } = series(row, days)
  let highest: { value: number; date: string } | null = null
  let lowest: { value: number; date: string } | null = null
  let over = 0, under = 0
  for (let index = 0; index < days; index++) {
    if (census[index] <= 0) continue
    const value = hours[index] / census[index]
    if (!highest || value > highest.value) highest = { value, date: dates[index] }
    if (!lowest || value < lowest.value) lowest = { value, date: dates[index] }
    if (hours[index] > targets[index]) over += 1
    else if (hours[index] < targets[index]) under += 1
  }
  return {
    ppd: ratio(sum(hours), sum(census)), target: ratio(sum(targets), sum(census)),
    highest, lowest, over, under,
  }
}

type Stats = ReturnType<typeof stats>
type Kind = 'ppd' | 'day' | 'count'
const metrics: [id: keyof Stats, header: string, kind: Kind][] = [
  ['ppd', 'Avg. HPPD', 'ppd'],
  ['target', 'Target HPPD', 'ppd'],
  ['highest', 'Highest day', 'day'],
  ['lowest', 'Lowest day', 'day'],
  ['over', 'Days over target', 'count'],
  ['under', 'Days under target', 'count'],
]

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'ppd' || kind === 'day') return ppdFormat(value)
  return value.toLocaleString()
}

/** HPPD's Trending tab: one role, or every role, drilled from state to
 * facility, each scope's trend read from its day-by-day HPPD -- its highest
 * and lowest day, the days over and under target --
 * and the scope's HPPD charted day over day against the range. The role and
 * the drilldown are kept in the URL. */
export function PpdTrending({ initialPath }: { initialPath?: string[] } = {}) {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // One drill= per level, in order; the Excel export's copy for a location starts there instead.
  const path = initialPath ?? params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    updated.delete('all_facilities')
    setParams(updated)
  }
  // The trend table's role filter: any set of roles, added up together, or with
  // none picked every role.
  const { roles, roleName, picker } = useStaffingRoles(TREND_ROLE_PARAM)

  const [data, setData] = useState<PpdTrend | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const rolesKey = roles.join(',')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getPpdTrend(startDate, endDate, rolesKey ? rolesKey.split(',') : [], controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, rolesKey, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error
  const dates = data?.dates ?? []

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The Excel export's sheet for each location in the table, this tab drilled into it.
  useLocationSheets(() => path.length === 4 ? [] : rows.map(row => ({ name: row.name,
    render: () => <PpdTrending initialPath={row.path} /> })))
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityTrend>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, numeric: true,
      header,
      value: row => {
        const value = stats(row, dates)[id]
        if (value === null) return '—'
        return typeof value === 'number' ? value : value.value
      },
      format: (value: number | string, row) => {
        if (kind !== 'day' || typeof value !== 'number') return format(value, kind)
        const found = stats(row, dates)[id] as { value: number; date: string } | null
        return found ? `${ppdFormat(found.value)} · ${day(found.date)}` : value
      },
    })),
  ]
  const range = `${startDate} to ${endDate}`
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const subtitle = `HPPD day by day, ${roleName}, ${range}. Each day's HPPD is that day's hours over its closing census; `
    + `Avg. HPPD is the range's hours over its census days. Days over and under target count the days hours were above or below `
    + 'the day\'s target hours.'
  const file = `${startDate}-to-${endDate}`

  // The chart follows the drilldown, as the table does: the facilities shown,
  // added up day by day, and always a point per day, whatever the range --
  // the weekend dips are the thing to see, and a block of days hides them.
  const scope: Row = { key: 'scope', name: scopeName, path: [], facilities: rows.flatMap(row => row.facilities) }
  const daily = series(scope, dates.length)
  const trend = dates.map((date, index) => ({ date, value: daily.census[index] > 0
      ? Math.round(daily.hours[index] / daily.census[index] * 100) / 100 : 0, census: daily.census[index] }))
    .filter(point => point.census > 0)
  const targetPpd = ratio(sum(daily.targets), sum(daily.census))

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} HPPD trend`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={picker}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`hppd-trend-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={picker}
      onSelect={next => setPath(next)}
      title={`All facilities · HPPD trend, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`hppd-trend-facilities-${file}.csv`} />
    <LineChart items={trend} title="HPPD day over day" valueLabel="HPPD"
      height={360} formatValue={ppdFormat}
      referenceLines={targetPpd === null ? [] : [
        { value: targetPpd * (1 + STAFFING_BAND), label: `Overstaffed ${ppdFormat(targetPpd * (1 + STAFFING_BAND))}`,
          tone: 'adverse' },
        { value: targetPpd, label: `Target ${ppdFormat(targetPpd)}` },
        { value: targetPpd * (1 - STAFFING_BAND), label: `Understaffed ${ppdFormat(targetPpd * (1 - STAFFING_BAND))}`,
          tone: 'adverse' },
      ]}
      subtitle={`${scopeName} · ${roleName} · Each day's hours over its census. The grey dashed line is the `
        + `target HPPD; the red ones are ${Math.round(STAFFING_BAND * 100)}% above and below it, overstaffed and `
        + 'understaffed.'}
      loading={loading} error={error} onRetry={onRetry} />
  </>
}
