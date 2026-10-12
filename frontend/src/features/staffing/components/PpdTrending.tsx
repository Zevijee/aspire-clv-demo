import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getPpdTrend, STAFFING_ROLES, TREND_ROLE_PARAM, type FacilityTrend, type PpdTrend } from '../api'

type Row = DrilldownRow<FacilityTrend>
// A week of days at each end of the range, compared to read the trend.
const EDGE_DAYS = 7
// How far from target counts as overstaffed or understaffed on the chart: a
// demo rule, 5% either side, not a regulatory line.
const STAFFING_BAND = 0.05
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const ppdFormat = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** The scope's series: the facilities' hours, targets and census added up
 * day by day, so any day's PPD is the scope's hours over its census. */
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
 * average of facility PPDs. */
function stats(row: Row, dates: string[]) {
  const days = dates.length
  const { hours, targets, census } = series(row, days)
  const edge = Math.min(EDGE_DAYS, days)
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
  const first = ratio(sum(hours, 0, edge), sum(census, 0, edge))
  const last = ratio(sum(hours, days - edge), sum(census, days - edge))
  return {
    ppd: ratio(sum(hours), sum(census)), target: ratio(sum(targets), sum(census)),
    first, last, change: first !== null && last !== null ? last - first : null,
    highest, lowest, over, under,
  }
}

type Stats = ReturnType<typeof stats>
type Kind = 'ppd' | 'change' | 'day' | 'count'
const metrics: [id: keyof Stats, header: string, kind: Kind][] = [
  ['ppd', 'Avg. PPD', 'ppd'],
  ['target', 'Target PPD', 'ppd'],
  ['first', `First ${EDGE_DAYS} days`, 'ppd'],
  ['last', `Last ${EDGE_DAYS} days`, 'ppd'],
  ['change', 'Change', 'change'],
  ['highest', 'Highest day', 'day'],
  ['lowest', 'Lowest day', 'day'],
  ['over', 'Days over target', 'count'],
  ['under', 'Days under target', 'count'],
]

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'ppd' || kind === 'day') return ppdFormat(value)
  if (kind === 'change') {
    // Rounded first, so a change too small to show reads 0.00, never −0.00.
    const shown = Math.round(value * 100) / 100
    return shown === 0 ? '0.00' : `${shown > 0 ? '+' : '−'}${Math.abs(shown).toFixed(2)}`
  }
  return value.toLocaleString()
}

/** PPD's Trending tab: one role, or every role, drilled from state to
 * facility, each scope's trend read from its day-by-day PPD -- its first and
 * last week, its highest and lowest day, the days over and under target --
 * and the scope's PPD charted day over day against the range. The role and
 * the drilldown are kept in the URL. */
export function PpdTrending() {
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
    updated.delete('all_facilities')
    setParams(updated)
  }
  // The bar's picker: any set of roles, added up together, or with none picked
  // every role. All roles clears the picks.
  const picks = useSearchParamList(TREND_ROLE_PARAM)
  const picked = picks.values.filter(code => STAFFING_ROLES.some(role => role.value === code))
  const roles = picked
  const roleName = roles.length
    ? STAFFING_ROLES.filter(role => roles.includes(role.value)).map(role => role.label).join(', ') : 'every role'
  const picker = <SegmentedControl fullWidth separate tone="accent" label="Roles"
    options={[{ id: 'all', label: 'All roles' }, ...STAFFING_ROLES.map(role => ({ id: role.value, label: role.label }))]}
    values={picked.length ? picked : ['all']}
    onChange={id => id === 'all' ? picks.clear() : picks.toggle(id)} />

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
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityTrend>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true,
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
      // Over target costs money and under it risks care: neither direction is good.
      ...(id === 'change' ? { change: { favorable: 'neutral' as const } } : {}),
    })),
  ]
  const range = `${startDate} to ${endDate}`
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const subtitle = `PPD day by day, ${roleName}, ${range}. Each day's PPD is that day's hours over its closing census; `
    + `Avg. PPD is the range's hours over its census days. The first and last ${EDGE_DAYS} days are each added up and `
    + 'divided once, and Change is the difference. Days over and under target count the days hours were above or below '
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
    <LocationNavigation path={path} setPath={setPath} controls={picker} />
    <DrilldownTable<Row> title={`${levels[depth]} PPD trend`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`ppd-trend-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · PPD trend, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`ppd-trend-facilities-${file}.csv`} />
    <LineChart items={trend} title="PPD day over day" valueLabel="PPD"
      height={360} formatValue={ppdFormat}
      referenceLines={targetPpd === null ? [] : [
        { value: targetPpd * (1 + STAFFING_BAND), label: `Overstaffed ${ppdFormat(targetPpd * (1 + STAFFING_BAND))}`,
          tone: 'adverse' },
        { value: targetPpd, label: `Target ${ppdFormat(targetPpd)}` },
        { value: targetPpd * (1 - STAFFING_BAND), label: `Understaffed ${ppdFormat(targetPpd * (1 - STAFFING_BAND))}`,
          tone: 'adverse' },
      ]}
      subtitle={`${scopeName} · ${roleName} · Each day's hours over its census. The grey dashed line is the `
        + `target PPD; the red ones are ${Math.round(STAFFING_BAND * 100)}% above and below it, overstaffed and `
        + 'understaffed.'}
      loading={loading} error={error} onRetry={onRetry} />
  </>
}
