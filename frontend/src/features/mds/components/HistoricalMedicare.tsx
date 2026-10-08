import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { LineChart } from '../../../shared/components/charts/LineChart'
import {
  getHistoricalCategories, getHistoricalDaily, getHistoricalMedicare, type CategoriesReport, type FacilityCategories,
  type FacilityHistorical, type HistoricalDailyTrend, type HistoricalMedicareReport,
} from '../api'
import { worksheetDateBasis } from '../worksheetApi'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../utils/locationDrilldown'
import { LocationNavigation } from './LocationNavigation'
import { CategoryCharts, categoryColumns, useCategoryControl } from './CategoryBreakdown'

/** What both tabs share, all from the URL: the date range, which date it
 * applies to, and the drilldown location -- so switching tab, a refresh or a
 * shared link keeps every one. */
function useHistoricalSelection() {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const dateBasis = worksheetDateBasis(params)
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
  return { startDate, endDate, dateBasis, path, setPath,
    basis: dateBasis === 'ard' ? 'whose 5-day ARD falls' : 'that started',
    basisLabel: dateBasis === 'ard' ? 'ARD' : 'stay start',
    range: `${startDate} to ${endDate}`, file: `${startDate}-to-${endDate}-by-${dateBasis}` }
}

/** One report fetched for the selection, again whenever it changes; not
 * until ready, while it waits on another. */
function useReport<Report>(load: (signal: AbortSignal) => Promise<Report>, keys: unknown[], ready = true) {
  const [data, setData] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!ready) return
    const controller = new AbortController()
    setError(null)
    load(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
    // keys name everything load reads, so load itself is left out.
  }, [...keys, ready, retry])
  return { data, error, loading: !data && !error, retry: () => setRetry(value => value + 1) }
}

/** The location column every drilldown here starts with: a link down a level
 * until the facility. */
function nameColumn<Item>(depth: number, path: string[], setPath: (path: string[]) => void): TableColumn<DrilldownRow<Item>> {
  return { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
}

type OverviewRow = DrilldownRow<FacilityHistorical>
type Summed = 'federal' | 'managed' | 'medicare_days' | 'actual_revenue' | 'neutral_revenue' | 'census_days'

function sum(row: OverviewRow, field: Summed) {
  return row.facilities.reduce((total, facility) => total + facility[field], 0)
}
// Sums at this scope divided once: never an average of facility averages.
// Rates are revenue per Medicare day, length of stay days per stay, average
// daily census census days per day of the range with census logs.
function metric(row: OverviewRow, field: string, rangeDays: number): number | null {
  const stays = sum(row, 'federal') + sum(row, 'managed')
  const days = sum(row, 'medicare_days')
  if (field === 'stays') return stays
  if (field === 'los') return stays > 0 ? days / stays : null
  if (field === 'adc') return rangeDays > 0 ? sum(row, 'census_days') / rangeDays : null
  if (field === 'neutral_rate') return days > 0 ? sum(row, 'neutral_revenue') / days : null
  if (field === 'actual_rate') return days > 0 ? sum(row, 'actual_revenue') / days : null
  return sum(row, field as Summed)
}

type Kind = 'count' | 'days' | 'average' | 'rate' | 'revenue'
// The Overview table's columns, after the location itself.
const metrics: [id: string, header: string, kind: Kind][] = [
  ['stays', 'PDPM stays', 'count'], ['federal', 'Federal Medicare', 'count'],
  ['managed', 'Managed Medicare PDPM', 'count'], ['los', 'Avg. length of stay', 'days'],
  ['census_days', 'Census days', 'count'], ['adc', 'Avg. daily census', 'average'],
  ['neutral_rate', 'Neutral rate', 'rate'], ['actual_rate', 'Actual rate', 'rate'],
  ['neutral_revenue', 'Neutral revenue', 'revenue'], ['actual_revenue', 'Actual revenue', 'revenue'],
]
function formatMetric(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  if (kind === 'revenue') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  const digits = kind === 'days' || kind === 'average' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** The Overview tab: the range's Medicare PDPM stays drilled from state to
 * facility -- how many, their length, the census over the range, and what
 * they were paid against the case-mix-neutral rate. */
export function HistoricalOverview() {
  const { startDate, endDate, dateBasis, path, setPath, basis, basisLabel, range, file } = useHistoricalSelection()
  const { data, error, loading, retry } = useReport<HistoricalMedicareReport>(
    signal => getHistoricalMedicare(startDate, endDate, dateBasis, signal), [startDate, endDate, dateBasis])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<OverviewRow>[] = [
    nameColumn<FacilityHistorical>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<OverviewRow> => ({
      id, header, numeric: true, value: row => metric(row, id, data?.census_range_days ?? 0) ?? '—',
      format: value => formatMetric(value, kind),
    })),
  ]
  const subtitle = data ? `Medicare PDPM stays ${basis} from ${range}: Original Medicare, and Managed `
    + 'Medicare PDPM. Managed Medicare PPO pays per diem and is not included. '
    + `Each stay counts whole, through its end or ${data.census_date} if still running. `
    + "Neutral rate is not adjusted for the facility's case mix; actual rate is what the payer paid. "
    + 'Rates are revenue per Medicare day. '
    + 'Census days are days inside the range a PDPM resident was in a bed, whenever their stay began, '
    + `so the date basis does not change them; average daily census divides them by the range's `
    + `${data.census_range_days.toLocaleString()} days with census data.` : ''

  // The trends follow the drilldown: every facility at the top, the ones under
  // the current path below it. Empty means all, so the top sends no id list.
  // Joined into a string so the fetch reruns only when the facilities change.
  const scopedIds = (path.length || grouping ? rows.flatMap(row => row.facilities.map(facility => facility.facility_id)) : [])
    .join(',')
  const trend = useReport<HistoricalDailyTrend>(
    signal => getHistoricalDaily(startDate, endDate, scopedIds ? scopedIds.split(',') : [], signal),
    [startDate, endDate, scopedIds], Boolean(data))
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  // It waits for the drilldown's facilities: before they load, a drilled path
  // has no ids yet and would fetch everyone's.
  const trendLoading = loading || trend.loading
  const trendDays = trend.data?.days ?? []
  const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD',
    maximumFractionDigits: 0 })
  const days = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 })

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<OverviewRow> title={`${levels[depth]} PDPM stays`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`historical-medicare-pdpm-${file}.csv`} />
    <AllFacilitiesModal<OverviewRow> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={path => setPath(path)}
      title={`All facilities · PDPM stays by ${basisLabel}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`historical-medicare-pdpm-facilities-${file}.csv`} />
    {/* Two to a row, on the same days, so a move in one reads against the others;
        each in its own colour so they are told apart at a glance. */}
    <div className="report-chart-grid">
      <LineChart title="PDPM census trending" valueLabel="PDPM census" variant="line" height={320}
        subtitle={`${scopeName}. PDPM residents in a bed each day, whenever their stay began; `
          + 'the date basis does not change it.'}
        items={trendDays.map(day => ({ date: day.date, value: day.census }))}
        loading={trendLoading} error={error ?? trend.error} onRetry={error ? retry : trend.retry} />
      <LineChart title="Neutral rate trending" valueLabel="Neutral rate" variant="line" height={320}
        subtitle={`${scopeName}. Average case-mix-neutral daily rate of those residents: the national `
          + 'per diem times their PDPM day factor.'}
        items={trendDays.filter(day => day.census > 0).map(day => ({ date: day.date, value: day.neutral_rates / day.census }))}
        // Its own colour, the accent the category buttons use, so the two charts
        // side by side are told apart at a glance.
        formatValue={money} lineColor="var(--color-accent)"
        loading={trendLoading} error={error ?? trend.error} onRetry={error ? retry : trend.retry} />
      <LineChart title="Actual rate trending" valueLabel="Actual rate" variant="line" height={320}
        subtitle={`${scopeName}. Average actual daily rate of those residents: what the payer paid.`}
        items={trendDays.filter(day => day.census > 0).map(day => ({ date: day.date, value: day.actual_rates / day.census }))}
        formatValue={money} lineColor="var(--color-chart-series-senary)"
        loading={trendLoading} error={error ?? trend.error} onRetry={error ? retry : trend.retry} />
      <LineChart title="Average length of stay trending" valueLabel="Avg. length of stay" variant="line" height={320}
        subtitle={`${scopeName}. Average days since admission of the PDPM residents in a bed each day, `
          + 'as Current Medicare PDPM counts length of stay.'}
        items={trendDays.filter(day => day.census > 0).map(day => ({ date: day.date, value: day.stay_days / day.census }))}
        formatValue={days} lineColor="var(--color-chart-series-quinary)"
        loading={trendLoading} error={error ?? trend.error} onRetry={error ? retry : trend.retry} />
    </div>
  </>
}

type CategoryRow = DrilldownRow<FacilityCategories>

/** The Category breakdown tab: the same stays counted by PDPM category, the
 * table's columns the chosen category's parts. */
export function HistoricalCategoryBreakdown() {
  const { startDate, endDate, dateBasis, path, setPath, basis, basisLabel, range, file } = useHistoricalSelection()
  const { data, error, loading, retry } = useReport<CategoriesReport>(
    signal => getHistoricalCategories(startDate, endDate, dateBasis, signal), [startDate, endDate, dateBasis])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { breakdown, control } = useCategoryControl()
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The location, then how many stays in each part of the chosen category.
  const columns: TableColumn<CategoryRow>[] = [
    nameColumn<FacilityCategories>(depth, path, setPath),
    ...categoryColumns<FacilityCategories>(breakdown),
  ]
  const subtitle = data ? `Medicare PDPM stays ${basis} from ${range}: Original Medicare, and Managed `
    + 'Medicare PDPM. Managed Medicare PPO pays per diem and is not included. Stays count by their 5-day '
    + `assessment once it is coded; stays not yet coded by ${data.census_date} are missing a care code `
    + `and counted in no ${breakdown.name.toLowerCase()} part.`
    + (breakdown.overlapping ? ' One stay can have several conditions, so the parts do not sum to the stays.' : '') : ''

  return <>
    {/* Every category shares one location path, so switching keeps where you are. */}
    <LocationNavigation path={path} setPath={setPath} controls={control} />
    <DrilldownTable<CategoryRow> title={`${breakdown.name} by ${levels[depth].toLowerCase()}`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`historical-medicare-pdpm-${breakdown.slug}-${file}.csv`} />
    <AllFacilitiesModal<CategoryRow> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={path => setPath(path)}
      title={`All facilities · ${breakdown.name}, PDPM stays by ${basisLabel}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`historical-medicare-pdpm-${breakdown.slug}-facilities-${file}.csv`} />
    <CategoryCharts<FacilityCategories> breakdown={breakdown} rows={rows} depth={depth}
      scopeName={path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'}
      unit={{ one: 'stay', many: 'stays' }}
      population={`PDPM stays ${basis} from ${range} with a care code`}
      fileSuffix={file} loading={loading} error={error} onRetry={retry} />
  </>
}
