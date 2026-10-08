import { useEffect, useState } from 'react'
import { CensusPayerFilter } from './CensusPayerFilter'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { groupLocations, useLocationView } from '../../../shared/customGrouping'
import type { TableColumn } from '../../../shared/components/Table'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { payerCode, payerLabel } from '../../adt/api/admissionsOverview'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { LookbackCards, type LookbackMeasure, type LookbackPeriod } from '../../../shared/components/LookbackCards'
import { getCensusTrendingDaily, getLiveCensus, type CensusDailyTrend, type FacilityCensus, type LiveCensusReport } from '../api'

type Row = { key: string; name: string; path: string[]; facilities: FacilityCensus[]; isTotal?: boolean }
type Summed = 'census' | 'all_census' | 'capacity' | 'skilled_census' | 'opening_census' | 'admissions'
  | 'discharges' | 'changes_in' | 'changes_out'
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
  // Closing less opening census: admissions less discharges, plus payer
  // changes in less out, which with no payer filter cancel.
  if (field === 'net_change') return census - (sum(row, 'opening_census') ?? 0)
  return sum(row, field as Summed)
}

const metrics: [id: string, header: string][] = [
  ['census', 'Census'], ['capacity', 'Capacity'], ['occupancy', 'Occupancy'],
  ['empty', 'Empty beds'], ['skilled_census', 'Skilled census'], ['skill_mix', 'Skill mix'],
  ['admissions', 'Admissions'], ['discharges', 'Discharges'],
  ['changes_in', 'Payer changes in'], ['changes_out', 'Payer changes out'], ['net_change', 'Net change'],
]
// Payer changes move residents between payer types inside a facility, so they
// change its census only when a payer filter narrows it; otherwise in equals out.
const payerChangeMetrics = new Set(['changes_in', 'changes_out'])
const fractional = new Set(['occupancy', 'skill_mix'])
const variances = new Set(['net_change'])

const percent = (value: number) => `${value.toLocaleString(undefined,
  { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
const shortDate = (value: string) => new Date(`${value}T00:00:00`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

export function LiveCensus() {
  const [response, setResponse] = useState<{ key: string; body: LiveCensusReport } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [path, setPath] = useState<string[]>([])
  const { grouping, locationView } = useLocationView(() => setPath([]))
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // The header's Payers filter, which the payer mix donut also sets.
  const [params, setParams] = useReportSearchParams()
  const payers = params.getAll('live_payer')
  // The header's date; absent means today.
  const censusDay = params.get('date')
  const requestKey = JSON.stringify([payers, censusDay])
  // Kept across the minute's refresh, dropped when the day or payers change, so
  // one day's numbers never show under another's date.
  const data = response?.key === requestKey ? response.body : null
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
    const [payerTypes, day] = JSON.parse(requestKey) as [string[], string | null]
    getLiveCensus(payerTypes, controller.signal, day)
      .then(body => { if (!controller.signal.aborted) setResponse({ key: requestKey, body }) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry, requestKey])
  const { depth, rows: groupRows } = groupLocations(data?.items ?? [], path, grouping)

  // Census over the 30 days to the census day, for the scope the drilldown
  // shows: each day's closing census, on the same payers -- the table's Census
  // column, day by day. Empty ids mean every
  // facility, so the top level sends none. Keyed by a string, so the minute's
  // refresh and a re-render do not refetch it.
  const trendIds = path.length || grouping
    ? groupRows.flatMap(row => row.facilities.map(facility => facility.facility_id)) : []
  const trendKey = data ? JSON.stringify([data.census_date, payers, trendIds]) : null
  const [trend, setTrend] = useState<{ key: string; data?: CensusDailyTrend; error?: string } | null>(null)
  useEffect(() => {
    if (!trendKey) return
    const controller = new AbortController()
    const [end, payerTypes, ids] = JSON.parse(trendKey) as [string, string[], string[]]
    const start = new Date(`${end}T00:00:00`)
    start.setDate(start.getDate() - 29)
    const startDate = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`
    void getCensusTrendingDaily(startDate, end, payerTypes, ids, controller.signal)
      .then(result => { if (!controller.signal.aborted) setTrend({ key: trendKey, data: result }) },
        (failure: Error) => { if (!controller.signal.aborted) setTrend({ key: trendKey, error: failure.message }) })
    return () => controller.abort()
  }, [trendKey])
  const currentTrend = trend?.key === trendKey ? trend : null
  const nameColumn: TableColumn<Row> = { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
  // The census history as look-back cards: current census against the same
  // averages as Current Medicare PDPM -- last month, the last 6 months, the
  // last year and all time -- with current minus each beside it, so a rise
  // reads as favourable, matching the table's variance. Each period sums its
  // facilities' census days first and divides once by the period's generated
  // days. Occupancy and skill mix divide the scope's sums once, as the table
  // does; beds are each facility's current count, which does not change.
  const periodDays = (key: string) => data?.periods.find(period => period.key === key)?.days ?? 0
  const historySum = (row: Row, key: string | null, field: 'census_days' | 'skilled_days') => {
    if (key === null) {
      return row.facilities.reduce((total, facility) =>
        total + (field === 'census_days' ? facility.census : facility.skilled_census), 0)
    }
    const days = periodDays(key)
    return days > 0 ? row.facilities.reduce((total, facility) => total + (facility.periods[key]?.[field] ?? 0), 0) / days
      : null
  }
  const historyCensus = (row: Row, key: string | null) => historySum(row, key, 'census_days')
  const historySkilled = (row: Row, key: string | null) => historySum(row, key, 'skilled_days')
  const points = (value: number) => `${value.toLocaleString(undefined,
    { minimumFractionDigits: 1, maximumFractionDigits: 1 })} pts`
  const historyMeasures: LookbackMeasure<Row>[] = [{
    id: 'census', label: 'Census', favorable: 'increase', step: 0.1,
    value: historyCensus,
    // Current census is a count; an average has a decimal place.
    format: (value, average) => value.toLocaleString(undefined,
      { minimumFractionDigits: average ? 1 : 0, maximumFractionDigits: average ? 1 : 0 }),
  }, {
    id: 'occupancy', label: 'Occupancy', favorable: 'increase', step: 0.1,
    value: (row, key) => {
      const census = historyCensus(row, key)
      const capacity = sum(row, 'capacity') ?? 0
      return census === null || capacity === 0 ? null : census / capacity * 100
    },
    format: percent, formatChange: points,
  }, {
    id: 'skill_mix', label: 'Skill mix', favorable: 'increase', step: 0.1,
    value: (row, key) => {
      const census = historyCensus(row, key)
      const skilled = historySkilled(row, key)
      return census === null || skilled === null || census === 0 ? null : skilled / census * 100
    },
    format: percent, formatChange: points,
  }]
  const historyPeriods: LookbackPeriod[] = (data?.periods ?? []).map(({ key, label, start, end }) =>
    ({ key, label, title: `${shortDate(start)} to ${shortDate(end)}`, average: true }))
  const columns: TableColumn<Row>[] = [
    nameColumn,
    ...metrics.filter(([id]) => payers.length > 0 || !payerChangeMetrics.has(id)).map(([id, header]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—',
      format: value => typeof value !== 'number' ? value : value.toLocaleString(undefined, {
        maximumFractionDigits: fractional.has(id) ? 1 : 0,
        minimumFractionDigits: fractional.has(id) ? 1 : 0,
        ...(variances.has(id) ? { signDisplay: 'exceptZero' as const } : {}),
      }) + (id === 'occupancy' || id === 'skill_mix' ? '%' : ''),
      ...(variances.has(id) ? { change: { favorable: 'increase' as const } } : {}),
    })),
  ]
  // The payer chart covers the same facilities as the table at its current level.
  const payerMix = new Map<string, number>()
  for (const facility of groupRows.flatMap(row => row.facilities)) {
    for (const [payer, census] of Object.entries(facility.payer_census)) {
      payerMix.set(payer, (payerMix.get(payer) ?? 0) + census)
    }
  }
  const payerItems = [...payerMix].map(([payer, value]) => ({ label: payerLabel(payer), value }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  const scopeFacilities = groupRows.flatMap(row => row.facilities)
  const scopeCensus = scopeFacilities.reduce((total, facility) => total + facility.census, 0)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  // One row per facility, whatever the drilldown above is showing.
  const facilityRows: Row[] = (data?.items ?? []).map(facility => ({
    key: facility.facility_id, name: facility.facility_name, path: location(facility), facilities: [facility] }))
  const stale = data && data.census_date < data.as_of
    ? ` Census is generated through ${data.census_date}, so that day's counts are shown.` : ''
  const subtitle = data ? `Census at the close of ${data.census_date}. Admissions, discharges and net change are that day's; `
    + 'net change is the closing census less the opening one'
    + (payers.length ? ', and with payers selected counts payer changes into and out of them.' : '.')
    + ` Skilled covers Medicare, managed Medicare and VA.${stale}` : ''
  const facilitiesModal = <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
    onSelect={path => { setPath(path); setShowFacilities(false) }}
    filters={<CensusPayerFilter param="live_payer" />}
    title={data ? `All facilities · census as of ${data.census_date}` : 'All facilities'} subtitle={subtitle}
    rows={facilityRows} columns={columns.slice(1)} getRowKey={row => row.key} getName={row => row.name}
    getPath={row => [row.path[0], row.path[1], row.path[2]]}
    loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
    csvFileName={`live-census-facilities-${data?.census_date ?? 'today'}.csv`} />

  return <>
    <DrilldownNavigation locationView={locationView} items={[
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} level={{ current: depth + 1, total: 4, label: levels[depth] }} />
    <DrilldownTable<Row> title={`${levels[depth]} census`} columns={columns} rows={groupRows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
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
      <LineChart title="Census, last 30 days" valueLabel="Census" variant="line" height={340}
        items={(currentTrend?.data?.days ?? []).map(day => ({ date: day.date, value: day.census }))}
        formatValue={value => Math.round(value).toLocaleString()}
        loading={!error && (!data || currentTrend === null)} error={error ?? currentTrend?.error ?? null}
        onRetry={() => { setRetry(value => value + 1); setTrend(null) }}
        subtitle={`${scopeName}, census at the close of each day${payers.length ? ', selected payers only' : ''}`
          + `${!data ? '' : `. ${shortDate(data.census_date)}: ${scopeCensus.toLocaleString()}`}`} />
    </div>
    {/* Each location's census on earlier days, with current minus each. Dates
        show on hovering a column's heading. */}
    <LookbackCards<Row> rows={groupRows} measures={historyMeasures}
      total={{ key: 'scope', name: scopeName, path, facilities: groupRows.flatMap(row => row.facilities), isTotal: true }}
      currentLabel="Current" currentTitle={data ? shortDate(data.census_date) : undefined} periods={historyPeriods}
      title={`${levels[depth]} census history`}
      subtitle="The current census against its average daily census over each earlier period; in brackets, the current census minus each average. Hover a column for its dates."
      csvFileName={`census-history-${data?.census_date ?? 'today'}.csv`}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)} />
  </>
}
