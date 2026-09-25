import { useEffect, useState } from 'react'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import type { TableColumn } from '../../../shared/components/Table'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { payerCode, payerLabel } from '../../adt/api/admissionsOverview'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { tableChange } from '../../../shared/utils/tableChange'
import { getLiveCensus, type FacilityCensus, type LiveCensusReport } from '../api'

type Row = { key: string; name: string; path: string[]; facilities: FacilityCensus[]; isTotal?: boolean }
type Summed = 'census' | 'all_census' | 'capacity' | 'skilled_census' | 'previous_average' | 'previous_skilled_average'
const levels = ['State', 'Portfolio', 'Region', 'Facility']
function location(row: FacilityCensus) { return [row.state, row.portfolio, row.region, row.facility_name] }

// Every facility's average divides by the same days, so summing facility
// averages gives the parent's average exactly -- not an average of averages.
function sum(row: Row, field: Summed): number | null {
  if (row.facilities.some(facility => facility[field] === null)) return null
  return row.facilities.reduce((total, facility) => total + (facility[field] ?? 0), 0)
}
function metric(row: Row, field: string): number | null {
  const census = sum(row, 'census') ?? 0
  const capacity = sum(row, 'capacity') ?? 0
  if (field === 'occupancy') return capacity > 0 ? census / capacity * 100 : null
  // Every resident holds a bed, whichever payers are selected.
  if (field === 'empty') return capacity - (sum(row, 'all_census') ?? 0)
  // A ratio of the two sums at this scope, never an average of facility ratios.
  if (field === 'skill_mix') return census > 0 ? (sum(row, 'skilled_census') ?? 0) / census * 100 : null
  if (field === 'variance') {
    const average = sum(row, 'previous_average')
    return average === null ? null : census - average
  }
  if (field === 'skilled_variance') {
    const average = sum(row, 'previous_skilled_average')
    return average === null ? null : (sum(row, 'skilled_census') ?? 0) - average
  }
  return sum(row, field as Summed)
}

const metrics: [id: string, header: string][] = [
  ['census', 'Census'], ['capacity', 'Capacity'], ['occupancy', 'Occupancy'],
  ['empty', 'Empty beds'], ['previous_average', 'Last month avg. daily census'],
  ['variance', 'Variance'], ['skilled_census', 'Skilled census'],
  ['skill_mix', 'Skill mix'],
  ['previous_skilled_average', 'Last month avg. daily skilled'], ['skilled_variance', 'Skilled variance'],
]
const fractional = new Set(['occupancy', 'skill_mix', 'previous_average', 'variance',
  'previous_skilled_average', 'skilled_variance'])
const variances = new Set(['variance', 'skilled_variance'])

const dollars = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

// A parent is only known when every facility under it is: one ungenerated day
// must not read as a smaller census.
function historySum(row: Row, value: (facility: FacilityCensus) => number | null): number | null {
  let total = 0
  for (const facility of row.facilities) {
    const next = value(facility)
    if (next === null) return null
    total += next
  }
  return total
}
const shortDate = (value: string) => new Date(`${value}T00:00:00`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

function monthLabel(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

export function LiveCensus() {
  const [data, setData] = useState<LiveCensusReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [path, setPath] = useState<string[]>([])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // The header's Payers filter, which the payer mix donut also sets.
  const [params, setParams] = useReportSearchParams()
  const payers = params.getAll('live_payer')
  const payerKey = JSON.stringify(payers)
  const setPayers = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('live_payer')
    next.forEach(payer => updated.append('live_payer', payer))
    setParams(updated)
  }
  useEffect(() => {
    const timer = window.setInterval(() => setRetry(value => value + 1), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getLiveCensus(JSON.parse(payerKey) as string[], controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry, payerKey])
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
  const nameColumn: TableColumn<Row> = { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
  const count = (value: number | string) => typeof value !== 'number' ? value : value.toLocaleString(undefined,
    { maximumFractionDigits: 0 })
  // Each past value carries its variance beside it: current minus then, so a
  // rise since then reads as favourable, matching the main table's variance.
  const withVariance = (digits: number) => (value: number | string, row: Row) => {
    if (typeof value !== 'number') return value
    const shown = value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    const change = tableChange(Math.round(((row.facilities.reduce((total, facility) => total + facility.census, 0))
      - value) * 10 ** digits) / 10 ** digits, 'increase')
    return <>{shown}<span className={`census-history__variance ${change.className ?? ''}`}>{change.text}</span></>
  }
  const historyColumns: TableColumn<Row>[] = [
    // Plain names: this table follows the level chosen above rather than
    // drilling on its own.
    { ...nameColumn, format: undefined },
    { id: 'current', header: 'Current', numeric: true, value: row => historySum(row, facility => facility.census) ?? '—', format: count },
    ...(data?.lookback ?? []).map(({ key, label }): TableColumn<Row> => ({
      id: key, header: label, numeric: true, format: withVariance(0),
      value: row => historySum(row, facility => facility.history[key] ?? null) ?? '—',
    })),
    { id: 'year_average', header: 'Last year avg.', numeric: true, format: withVariance(1),
      value: row => historySum(row, facility => facility.year_average) ?? '—' },
  ]
  const columns: TableColumn<Row>[] = [
    nameColumn,
    ...metrics.map(([id, header]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—',
      format: value => typeof value !== 'number' ? value : value.toLocaleString(undefined, {
        maximumFractionDigits: fractional.has(id) ? 1 : 0,
        minimumFractionDigits: fractional.has(id) ? 1 : 0,
        ...(variances.has(id) ? { signDisplay: 'exceptZero' as const } : {}),
      }) + (id === 'occupancy' || id === 'skill_mix' ? '%' : ''),
      ...(variances.has(id) ? { change: { favorable: 'increase' as const } } : {}),
    })),
  ]
  // The payer charts cover the same facilities as the table at its current level.
  const payerMix = new Map<string, number>()
  const payerRates = new Map<string, number>()
  for (const facility of [...groups.values()].flatMap(row => row.facilities)) {
    for (const [payer, census] of Object.entries(facility.payer_census)) {
      payerMix.set(payer, (payerMix.get(payer) ?? 0) + census)
    }
    for (const [payer, rates] of Object.entries(facility.payer_daily_rates)) {
      payerRates.set(payer, (payerRates.get(payer) ?? 0) + rates)
    }
  }
  const payerItems = [...payerMix].map(([payer, value]) => ({ label: payerLabel(payer), value }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  // Every resident's rate summed, then divided once by residents: a resident-
  // weighted average, never an average of facility or plan averages.
  const rateItems = [...payerMix].filter(([, census]) => census > 0)
    .map(([payer, census]) => ({ label: payerLabel(payer), value: (payerRates.get(payer) ?? 0) / census }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  const residents = [...payerMix.values()].reduce((total, value) => total + value, 0)
  const blendedRate = residents > 0
    ? [...payerRates.values()].reduce((total, value) => total + value, 0) / residents : null
  const scopeName = path.length ? path[path.length - 1] : 'All locations'
  // One row per facility, whatever the drilldown above is showing.
  const facilityRows: Row[] = (data?.items ?? []).map(facility => ({
    key: facility.facility_id, name: facility.facility_name, path: location(facility), facilities: [facility] }))
  const stale = data && data.census_date < data.as_of
    ? ` Census is generated through ${data.census_date}, so that day's counts are shown.` : ''
  const incomplete = data?.items.some(item => item.previous_average === null)
    ? ' Last month is not completely generated, so its averages are unavailable.' : ''
  const subtitle = data ? `Census as of ${data.census_date}. Last month: ${monthLabel(data.previous_month)}. `
    + "Variance is current census minus last month's average daily census. "
    + `Skilled covers Medicare, managed Medicare and VA.${stale}${incomplete}` : ''

  const facilitiesModal = <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
    title={data ? `All facilities · census as of ${data.census_date}` : 'All facilities'} subtitle={subtitle}
    rows={facilityRows} columns={columns.slice(1)} getRowKey={row => row.key} getName={row => row.name}
    getPath={row => [row.path[0], row.path[1], row.path[2]]}
    loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
    csvFileName={`live-census-facilities-${data?.census_date ?? 'today'}.csv`} />

  return <>
    <DrilldownNavigation locationView={{
      groupBy: 'state', selectedCount: 0,
      onReturn: () => setPath([]),
      onClear: () => setPath([]),
    }} items={[
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} level={{ current: depth + 1, total: 4, label: levels[depth] }} />
    <DrilldownTable<Row> title={`${levels[depth]} census`} columns={columns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`live-census-${data?.census_date ?? 'today'}.csv`} />
    {facilitiesModal}
    <div className="report-chart-grid">
      <DonutChart loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
        title="Payer mix" valueLabel="Residents" items={payerItems}
        subtitle={`${scopeName}${data ? `, as of ${data.census_date}` : ''}. Click payers to filter the report`}
        selectedLabels={payers.map(payerLabel)} onClear={() => setPayers([])}
        onSelect={label => {
          const payer = payerCode(label)
          setPayers(payers.includes(payer) ? payers.filter(value => value !== payer) : [...payers, payer])
        }} />
      <BarChartRanking loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
        title="Average daily rate by payer" categoryLabel="Payer" valueLabel="per resident per day"
        selectedLabels={payers.map(payerLabel)}
        items={rateItems} formatValue={dollars} showShare={false}
        subtitle={`${scopeName}, residents in a bed that day${blendedRate === null ? ''
          : `. All payers: ${dollars(blendedRate)}`}`} />
    </div>
    <DrilldownTable<Row> title={`${levels[depth]} census history`} columns={historyColumns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={data ? 'Census at the close of each day, with current census minus that value beside it. '
        + `Current: ${shortDate(data.census_date)}; `
        + data.lookback.map(entry => `${entry.label.toLowerCase()}: ${shortDate(entry.date)}`).join('; ')
        + `. Last year avg. is the average daily census from ${shortDate(data.year_start)} to ${shortDate(data.year_end)}.` : ''}
      emptyMessage="No facilities match this view."
      csvFileName={`census-history-${data?.census_date ?? 'today'}.csv`} />
  </>
}
