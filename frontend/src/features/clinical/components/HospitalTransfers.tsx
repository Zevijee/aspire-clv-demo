import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { payerCode, payerLabels } from '../../adt/api/admissionsOverview'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { groupTrendPeriods, trendBlockSize } from '../../../shared/utils/trendPeriods'
import {
  getDailyTransfers, getHospitalTransfers, type DailyTransfers, type FacilityTransfers, type HospitalTransfersReport,
} from '../api'

type Row = DrilldownRow<FacilityTransfers>
type Summed = 'transfers' | 'within_30_days' | 'los_days' | 'rehospitalizations' | 'resident_days'
// The donuts' filters, kept in the URL with the drilldown.
const PAYER_PARAM = 'transfer_payer'
const REASON_PARAM = 'transfer_reason'

const sum = (row: Row, field: Summed) => row.facilities.reduce((total, facility) => total + facility[field], 0)
// Sums at this scope divided once: never an average of facility averages.
function metric(row: Row, id: string): number | null {
  const transfers = sum(row, 'transfers')
  if (id === 'los') return transfers > 0 ? sum(row, 'los_days') / transfers : null
  // The prior period is unknown when its days were never generated.
  if (id === 'prior' || id === 'variance') {
    if (row.facilities.some(facility => facility.prior_transfers === null)) return null
    const prior = row.facilities.reduce((total, facility) => total + (facility.prior_transfers ?? 0), 0)
    return id === 'prior' ? prior : transfers - prior
  }
  if (id === 'rate') {
    const days = sum(row, 'resident_days')
    return days > 0 ? transfers / days * 1000 : null
  }
  return sum(row, id as Summed)
}

type Kind = 'count' | 'days' | 'rate'
const metrics: [id: string, header: string, kind: Kind][] = [
  ['transfers', 'Hospital transfers', 'count'],
  ['prior', 'Prior transfers', 'count'],
  ['variance', 'Variance vs prior', 'count'],
  ['within_30_days', 'Within 30 days of admission', 'count'],
  ['los', 'Avg. length of stay', 'days'],
  ['rehospitalizations', 'Rehospitalizations', 'count'],
  ['rate', 'Transfers per 1,000 resident days', 'rate'],
]
function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  const digits = kind === 'days' ? 1 : kind === 'rate' ? 2 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** Hospital Transfers: residents sent to a hospital in the header's date range,
 * drilled from state to facility -- how many, how many soon after admission,
 * how long they had stayed, the rehospitalizations among them, and the rate per
 * 1,000 resident days. The drilldown is kept in the URL. */
export function HospitalTransfers() {
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
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<HospitalTransfersReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const payerFilter = params.getAll(PAYER_PARAM)
  const reasonFilter = params.getAll(REASON_PARAM)
  // Joined, so the fetch reruns only when a filter changes.
  const filterKey = JSON.stringify([payerFilter, reasonFilter])
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getHospitalTransfers(startDate, endDate, payerFilter, reasonFilter, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
    // filterKey names both filters.
  }, [startDate, endDate, filterKey, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityTransfers>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—',
      // Fewer transfers than before is the good direction.
      ...(id === 'variance' ? { change: { favorable: 'decrease' as const } }
        : { format: (value: number | string) => format(value, kind) }),
    })),
  ]
  const range = `${startDate} to ${endDate}`
  const filtered = [...payerFilter.map(payer => payerLabels[payer] ?? payer), ...reasonFilter]
  const priorRange = data ? `${data.prior_start_date} to ${data.prior_end_date}` : 'the period before'
  const subtitle = `Discharges to a hospital from ${range}${filtered.length ? `, filtered to ${filtered.join(', ')}` : ''}. `
    + `Prior transfers are the same days just before, ${priorRange}, with the same filters. `
    + 'Within 30 days counts transfers no more than 30 days '
    + 'after admission. Length of stay is the days from admission to the transfer. A rehospitalization is a '
    + 'resident admitted from a hospital and sent back to one within 30 days. The rate is transfers per 1,000 '
    + 'resident days, each day\'s census summed over the range.'
  const file = `${startDate}-to-${endDate}`
  // The breakdowns follow the drilldown and custom grouping, as the table does:
  // the facilities shown, their counts added up, largest first.
  const scoped = rows.flatMap(row => row.facilities)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const breakdown = (field: 'payers' | 'reasons', label: (key: string) => string) => {
    const totals = new Map<string, number>()
    for (const facility of scoped) {
      for (const [key, count] of Object.entries(facility[field])) totals.set(key, (totals.get(key) ?? 0) + count)
    }
    return [...totals].map(([key, value]) => ({ label: label(key), value }))
      .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  }
  const status = { loading, error, onRetry }

  // The daily trend follows the same filters and the drilldown: every facility
  // at the top, the ones shown below it. Joined into a string so the fetch reruns
  // only when the facilities change; it waits for the table, which knows them.
  const scopedIds = (path.length || grouping ? scoped.map(facility => facility.facility_id) : []).join(',')
  const [daily, setDaily] = useState<DailyTransfers | null>(null)
  const [dailyError, setDailyError] = useState<string | null>(null)
  const [dailyRetry, setDailyRetry] = useState(0)
  useEffect(() => {
    if (!data) return
    const controller = new AbortController()
    setDailyError(null)
    getDailyTransfers(startDate, endDate, payerFilter, reasonFilter, scopedIds ? scopedIds.split(',') : [],
      controller.signal)
      .then(body => { if (!controller.signal.aborted) setDaily(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setDailyError(failure.message) })
    return () => controller.abort()
    // filterKey and scopedIds name everything the request reads.
  }, [startDate, endDate, filterKey, scopedIds, Boolean(data), dailyRetry])
  // Long ranges are shown in equal blocks of days, as Daily Admissions is.
  const blockSize = trendBlockSize(startDate, endDate)
  const trend = groupTrendPeriods((daily?.days ?? []).map(day => ({ date: day.date, value: day.transfers })),
    startDate, blockSize)
  // A slice toggles its value in the filter; the filters live in the URL.
  const toggle = (param: string, value: string) => {
    const next = new URLSearchParams(params)
    const values = next.getAll(param)
    next.delete(param)
    ;(values.includes(value) ? values.filter(item => item !== value) : [...values, value])
      .forEach(item => next.append(param, item))
    setParams(next)
  }
  const clear = (param: string) => {
    const next = new URLSearchParams(params)
    next.delete(param)
    setParams(next)
  }

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} hospital transfers`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`hospital-transfers-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · Hospital transfers, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`hospital-transfers-facilities-${file}.csv`} />
    <div className="report-chart-grid">
      {/* Each filters the report and keeps all of its own slices, as the
          Admissions payer donut does. */}
      <DonutChart {...status} title="Transfers by payer" valueLabel="Transfers"
        subtitle={`${scopeName} · Click payers to filter the report`}
        items={breakdown('payers', key => payerLabels[key] ?? key)}
        selectedLabels={payerFilter.map(payer => payerLabels[payer] ?? payer)} onClear={() => clear(PAYER_PARAM)}
        onSelect={label => toggle(PAYER_PARAM, payerCode(label))} />
      <DonutChart {...status} title="Transfers by reason" valueLabel="Transfers"
        subtitle={`${scopeName} · Click reasons to filter the report`}
        items={breakdown('reasons', key => key)}
        selectedLabels={reasonFilter} onClear={() => clear(REASON_PARAM)}
        filterName={{ one: 'reason', many: 'reasons' }}
        onSelect={label => toggle(REASON_PARAM, label)} />
    </div>
    <LineChart items={trend} title={blockSize === 1 ? 'Daily hospital transfers' : 'Hospital transfers trend'}
      // Red, the shared adverse colour: transfers are a count to bring down.
      valueLabel="Transfers" variant="bar" height={360} barColor="var(--color-table-change-adverse)"
      subtitle={`${scopeName} · ${blockSize === 1 ? 'Hospital transfers each day'
        : `Hospital transfers per ${blockSize}-day period; the tooltip shows the exact dates`}${filtered.length
        ? `, filtered to ${filtered.join(', ')}` : ''}.`}
      loading={loading || (!daily && !dailyError)} error={error ?? dailyError}
      onRetry={error ? onRetry : () => setDailyRetry(count => count + 1)} />
  </>
}
