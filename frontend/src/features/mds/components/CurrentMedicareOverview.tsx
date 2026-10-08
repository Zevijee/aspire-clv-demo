import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { LookbackCards, type LookbackMeasure } from '../../../shared/components/LookbackCards'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import {
  getMedicareLookback, getMedicareOverview, type FacilityLookback, type FacilityOverview,
  type MedicareLookbackReport, type OverviewReport,
} from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../../../shared/utils/locationDrilldown'
import { LocationNavigation } from '../../../shared/components/LocationNavigation'

type Row = DrilldownRow<FacilityOverview>
type Summed = 'federal' | 'managed' | 'actual_rates' | 'neutral_rates' | 'resident_days' | 'no_score'
  | 'no_score_days'

function sum(row: Row, field: Summed) {
  return row.facilities.reduce((total, facility) => total + facility[field], 0)
}
// Sums at this scope divided once by its residents: never an average of
// facility averages.
function metric(row: Row, field: string): number | null {
  const residents = sum(row, 'federal') + sum(row, 'managed')
  if (field === 'residents') return residents
  if (field === 'neutral_rate') return residents > 0 ? sum(row, 'neutral_rates') / residents : null
  if (field === 'actual_rate') return residents > 0 ? sum(row, 'actual_rates') / residents : null
  if (field === 'los') return residents > 0 ? sum(row, 'resident_days') / residents : null
  if (field === 'missing_los') {
    const missing = sum(row, 'no_score')
    return missing > 0 ? sum(row, 'no_score_days') / missing : null
  }
  return sum(row, field as Summed)
}

// The location table's columns, after the location itself.
const metrics: [id: string, header: string, kind: 'count' | 'rate' | 'days'][] = [
  ['residents', 'PDPM residents', 'count'], ['federal', 'Federal Medicare', 'count'],
  ['managed', 'Managed Medicare PDPM', 'count'], ['no_score', 'Missing care code', 'count'],
  ['missing_los', 'Avg. LOS, missing care code', 'days'],
  ['neutral_rate', 'Neutral rate', 'rate'], ['actual_rate', 'Actual rate', 'rate'],
  ['los', 'Avg. length of stay', 'days'],
]
const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
function formatMetric(value: number | string, kind: 'count' | 'rate' | 'days') {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return money(value)
  const digits = kind === 'days' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

type LookbackRow = DrilldownRow<FacilityLookback>
// What every look-back card shows, side by side. Residents is a count; the
// rates divide the scope's summed rates by its resident-days. A rise in any of
// them against the average reads as favourable.
const measures = [
  { id: 'residents', label: 'PDPM residents', favorable: 'increase' },
  { id: 'neutral', label: 'Neutral rate', favorable: 'increase' },
  { id: 'actual', label: 'Actual rate', favorable: 'increase' },
] as const
type Measure = (typeof measures)[number]['id']

/** A period's value of the measure at a scope, summed over its facilities and
 * divided once: residents per generated day, rates per resident-day. */
function periodValue(row: LookbackRow, measure: Measure, key: string, days: number) {
  let residentDays = 0, actual = 0, neutral = 0
  for (const facility of row.facilities) {
    const totals = facility.periods[key]
    if (!totals) return null
    residentDays += totals.resident_days
    actual += totals.actual_rates
    neutral += totals.neutral_rates
  }
  if (measure === 'residents') return days > 0 ? residentDays / days : null
  if (residentDays === 0) return null
  return (measure === 'actual' ? actual : neutral) / residentDays
}

const shortDate = (value: string) => new Date(`${value}T00:00:00`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

/** The Overview tab: today's PDPM residents and rates by location, and the
 * same scope looked back on -- yesterday to a year ago -- with how today
 * differs from each. */
export function CurrentMedicareOverview() {
  const [params, setParams] = useReportSearchParams()
  // The drilldown location, kept in the URL (one drill= per level, in order),
  // shared with the Category breakdown tab so switching keeps it.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<OverviewReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [past, setPast] = useState<MedicareLookbackReport | null>(null)
  const [pastError, setPastError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    setPastError(null)
    getMedicareOverview(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    // Apart, so the look-back loading never holds up today's table.
    getMedicareLookback(controller.signal)
      .then(body => { if (!controller.signal.aborted) setPast(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setPastError(failure.message) })
    return () => controller.abort()
  }, [retry])
  const retryLoad = () => setRetry(value => value + 1)

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—', format: value => formatMetric(value, kind),
    })),
  ]
  const loading = !data && !error
  const subtitle = data ? `Residents paid from their PDPM code on ${data.census_date}: Original Medicare, `
    + 'and Managed Medicare PDPM. Managed Medicare PPO pays per diem and is not included. '
    + 'Missing care code is residents not yet assessed and coded in the first days of their Medicare stay. '
    + "Neutral rate is not adjusted for the facility's case mix. Actual rate is what the payer pays." : ''

  // The look-back follows the same drilldown: one card per location at this
  // level, the scope's own total first. A card's name drills in, as the
  // table's names do.
  const { rows: pastRows } = groupByLocation(past?.items ?? [], path, grouping)
  const pastLoading = !past && !pastError
  const scopeRow: LookbackRow = { key: 'scope', name: path.length ? path[path.length - 1]
    : grouping ? 'Custom grouping' : 'All locations', path, facilities: pastRows.flatMap(row => row.facilities),
    isTotal: true }
  // The periods after today, each an average over its generated days.
  const averages = (past?.periods ?? []).filter(period => period.key !== 'today')
  const lookbackMeasures = measures.map(({ id, label, favorable }): LookbackMeasure<LookbackRow> => ({
    id, label, favorable,
    value: (row, key) => key === null ? periodValue(row, id, 'today', 1)
      : periodValue(row, id, key, averages.find(period => period.key === key)?.days ?? 0),
    // Today's residents are a count; an average has a decimal place.
    format: (value, average) => id !== 'residents' ? money(value) : value.toLocaleString(undefined,
      { minimumFractionDigits: average ? 1 : 0, maximumFractionDigits: average ? 1 : 0 }),
    // Cents for a rate, tenths of a resident against an average.
    step: id === 'residents' ? 0.1 : 0.01,
  }))

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} PDPM residents`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retryLoad}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicare-${data?.census_date ?? 'today'}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={path => setPath(path)}
      title={data ? `All facilities · PDPM residents on ${data.census_date}` : 'All facilities'} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retryLoad}
      csvFileName={`current-medicare-facilities-${data?.census_date ?? 'today'}.csv`} />
    {/* Floating on the page, two to a row: each location's own look-back,
        today against earlier days, with today minus each beside it. */}
    <LookbackCards<LookbackRow> rows={pastRows} total={scopeRow} measures={lookbackMeasures}
      currentLabel="Today" currentTitle={past ? shortDate(past.census_date) : undefined}
      periods={averages.map(({ key, label, start, end }) =>
        ({ key, label, title: `${shortDate(start)} to ${shortDate(end)}`, average: true }))}
      title={`${levels[depth]} PDPM look-back`}
      subtitle={'PDPM residents, and their average neutral and actual daily rates, today against last month, the '
        + "last 6 months, the last year and all time; in brackets, today minus each average. Hover a column for its dates."}
      csvFileName={`current-medicare-lookback-${past?.census_date ?? 'today'}.csv`}
      loading={pastLoading} error={pastError} onRetry={retryLoad} />
  </>
}
