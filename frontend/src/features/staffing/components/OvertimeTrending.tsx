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
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getOvertimeTrend, OVERTIME_ROLE_PARAM, type FacilityOvertimeTrend, type OvertimeTrend } from '../api'
import { useStaffingRoles } from './StaffingRolePicker'

type Row = DrilldownRow<FacilityOvertimeTrend>
// What an overtime hour costs over straight time, as a share of its pay: the
// API's rule, repeated for the trend's premium column.
const PREMIUM = 0.5
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const percent = (value: number) => `${(value * 100).toLocaleString(undefined,
  { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`

/** The scope's series: the facilities' hours, overtime hours and the
 * overtime's pay added up day by day, so any day's share is the scope's
 * overtime over its hours. */
function series(row: Row, days: number) {
  const hours = new Array<number>(days).fill(0)
  const overtime = new Array<number>(days).fill(0)
  const wages = new Array<number>(days).fill(0)
  for (const facility of row.facilities) {
    for (let index = 0; index < days; index++) {
      hours[index] += facility.hours[index] ?? 0
      overtime[index] += facility.overtime_hours[index] ?? 0
      wages[index] += facility.overtime_wages[index] ?? 0
    }
  }
  return { hours, overtime, wages }
}

const ratio = (numerator: number, denominator: number) => denominator > 0 ? numerator / denominator : null
const sum = (values: number[], from = 0, to = values.length) => {
  let total = 0
  for (let index = from; index < to; index++) total += values[index]
  return total
}

/** The trend's figures at one scope, each a sum divided once: never an
 * average of facility shares. */
function stats(row: Row, dates: string[]) {
  const days = dates.length
  const { hours, overtime, wages } = series(row, days)
  let highest: { value: number; date: string } | null = null
  for (let index = 0; index < days; index++) {
    if (hours[index] <= 0) continue
    const value = overtime[index] / hours[index]
    if (!highest || value > highest.value) highest = { value, date: dates[index] }
  }
  const shareOf = (from: number, to: number) => ratio(sum(overtime, from, to), sum(hours, from, to))
  return {
    overtime: sum(overtime), premium: sum(wages) * PREMIUM, share: shareOf(0, days),
    highest,
  }
}

type Stats = ReturnType<typeof stats>
type Kind = 'hours' | 'money' | 'share' | 'day'
const metrics: [id: keyof Stats, header: string, kind: Kind][] = [
  ['overtime', 'Overtime hours', 'hours'],
  ['premium', 'Overtime premium', 'money'],
  ['share', 'Overtime share', 'share'],
  ['highest', 'Highest day', 'day'],
]

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'share' || kind === 'day') return percent(value)
  if (kind === 'money') return `$${Math.round(value).toLocaleString()}`
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

/** Overtime's Trending tab: how much of the work is overtime, drilled from
 * state to facility, each scope's trend read from its day-by-day overtime
 * share -- its highest day -- and the scope's share
 * charted day over day. A day's overtime is its share of each employee's
 * overtime for the week, spread over the days they worked. The drilldown is kept in the URL. */
export function OvertimeTrending() {
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
  const [data, setData] = useState<OvertimeTrend | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // The trend table's role filter: the chosen roles added up by the API, or every role.
  const { roles, roleName, picker } = useStaffingRoles(OVERTIME_ROLE_PARAM)
  const rolesKey = roles.join(',')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getOvertimeTrend(startDate, endDate, rolesKey ? rolesKey.split(',') : [], controller.signal)
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
    locationColumn<FacilityOvertimeTrend>(depth, path, setPath),
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
        return found ? `${percent(found.value)} · ${day(found.date)}` : value
      },
    })),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const subtitle = `Overtime day by day, ${roleName}, ${range}. A day's overtime is its share of each employee's hours `
    + 'over 40 for the week, spread over the days they worked; the share is that over the day\'s '
    + `hours, and Overtime share is the range's. Overtime premium is what time-and-a-half would add.`
    + ``
  const file = `${shownStart}-to-${shownEnd}`

  // The chart follows the drilldown, as the table does: the facilities shown,
  // added up day by day, a point per day whatever the range -- the build
  // through each week is the thing to see.
  const scope: Row = { key: 'scope', name: scopeName, path: [], facilities: rows.flatMap(row => row.facilities) }
  const daily = series(scope, dates.length)
  const hoursLabel = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })} h`
  const money = (value: number) => `$${Math.round(value).toLocaleString()}`
  // Each day's overtime as a share of its hours, with the figures behind it
  // for the tooltip: the overtime hours, the day's hours and the premium.
  const trend = dates.map((date, index) => ({ date, total: daily.hours[index],
    value: daily.hours[index] > 0 ? Math.round(daily.overtime[index] / daily.hours[index] * 1000) / 10 : 0,
    details: [
      { label: 'Overtime hours', value: hoursLabel(daily.overtime[index]) },
      { label: 'Hours worked', value: hoursLabel(daily.hours[index]) },
      { label: 'Overtime premium', value: money(daily.wages[index] * PREMIUM) },
    ] })).filter(point => point.total > 0)
  const average = ratio(sum(daily.overtime), sum(daily.hours))
  const percentPoints = (value: number) => `${value.toLocaleString(undefined,
    { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} overtime trend`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={picker}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`overtime-trend-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={picker}
      onSelect={next => setPath(next)}
      title={`All facilities · Overtime trend, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`overtime-trend-facilities-${file}.csv`} />
    <LineChart items={trend} title="Overtime share day over day" valueLabel="Overtime share"
      height={360} formatValue={percentPoints}
      referenceLines={average === null ? [] : [
        { value: Math.round(average * 1000) / 10, label: `Range ${percent(average)}` },
      ]}
      subtitle={`${scopeName} · ${roleName} · Each day's overtime hours as a share of its hours worked, each `
        + 'employee\'s hours over 40 for the week spread over the days they worked. The dashed line is the range\'s '
        + 'share, every day added up and divided once. Hover a day for its hours and premium.'}
      loading={loading} error={error} onRetry={onRetry} />
  </>
}
