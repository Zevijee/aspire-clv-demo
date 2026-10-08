import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { LocationName } from '../../../shared/components/LocationName'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { LineChart } from '../../../shared/components/charts/LineChart'
import {
  downloadHistoricalMedicaidResidents, getHistoricalMedicaid, getHistoricalMedicaidCategories,
  getHistoricalMedicaidDaily, getHistoricalMedicaidResidents, historicalMedicaidResidentFilterOptions,
  type FacilityHistoricalMedicaid, type FacilityMedicaidCategories, type HistoricalMedicaidDaily,
  type HistoricalMedicaidReport, type HistoricalMedicaidResident, type MedicaidCategoriesReport,
  type MedicareResidentsQuery,
} from '../api'
import { worksheetDateBasis } from '../worksheetApi'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../../../shared/utils/locationDrilldown'
import { LocationNavigation, locationColumn as nameColumn } from '../../../shared/components/LocationNavigation'
import { CategoryCharts, categoryColumns, useCategoryControl } from './CategoryBreakdown'
import { useReport } from './HistoricalMedicare'
import { medicaidCategories, residentLocationFilters, useDrillPath } from './CurrentMedicaid'

const scopeNote = 'Texas Medicaid stays, whose Medicaid pays on the PDPM nursing and NTA components; Florida and '
  + 'Pennsylvania use other systems and are not included.'

/** What every tab shares, all from the URL: the date range, which date it
 * applies to, and the drilldown location -- Texas until another is chosen. */
function useHistoricalMedicaidSelection() {
  const [params] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const dateBasis = worksheetDateBasis(params)
  return { startDate, endDate, dateBasis, ...useDrillPath(),
    basis: dateBasis === 'ard' ? 'whose first assessment ARD falls' : 'that started',
    basisLabel: dateBasis === 'ard' ? 'ARD' : 'stay start',
    range: `${startDate} to ${endDate}`, file: `${startDate}-to-${endDate}-by-${dateBasis}` }
}

type OverviewRow = DrilldownRow<FacilityHistoricalMedicaid>
type Summed = 'stays' | 'medicaid_days' | 'actual_revenue' | 'census_days'

const sum = (row: OverviewRow, field: Summed) => row.facilities.reduce((total, facility) => total + facility[field], 0)
// Sums at this scope divided once: never an average of facility averages. The
// rate is revenue per Medicaid day, length of stay days per stay, average
// daily census census days per day of the range with census logs.
function metric(row: OverviewRow, field: string, rangeDays: number): number | null {
  const stays = sum(row, 'stays')
  const days = sum(row, 'medicaid_days')
  if (field === 'los') return stays > 0 ? days / stays : null
  if (field === 'adc') return rangeDays > 0 ? sum(row, 'census_days') / rangeDays : null
  if (field === 'actual_rate') return days > 0 ? sum(row, 'actual_revenue') / days : null
  return sum(row, field as Summed)
}

type Kind = 'count' | 'days' | 'average' | 'rate' | 'revenue'
// No neutral rate: Medicaid pays its own rate, which no case-mix-neutral rate
// compares with here.
const metrics: [id: string, header: string, kind: Kind][] = [
  ['stays', 'Medicaid stays', 'count'], ['los', 'Avg. length of stay', 'days'],
  ['census_days', 'Census days', 'count'], ['adc', 'Avg. daily census', 'average'],
  ['actual_rate', 'Actual rate', 'rate'], ['actual_revenue', 'Actual revenue', 'revenue'],
]
function formatMetric(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  if (kind === 'revenue') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  const digits = kind === 'days' || kind === 'average' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** The Overview tab: the range's Texas Medicaid stays drilled from Texas to
 * facility -- how many, their length, the census over the range and what
 * Medicaid paid -- and the census, rate and length of stay day by day. */
export function HistoricalMedicaidOverview() {
  const { startDate, endDate, dateBasis, path, setPath, basis, basisLabel, range, file } = useHistoricalMedicaidSelection()
  const { data, error, loading, retry } = useReport<HistoricalMedicaidReport>(
    signal => getHistoricalMedicaid(startDate, endDate, dateBasis, signal), [startDate, endDate, dateBasis])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<OverviewRow>[] = [
    nameColumn<FacilityHistoricalMedicaid>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<OverviewRow> => ({
      id, header, numeric: true, value: row => metric(row, id, data?.census_range_days ?? 0) ?? '—',
      format: value => formatMetric(value, kind),
    })),
  ]
  const subtitle = data ? `${scopeNote} Stays ${basis} from ${range}, each counted whole, through its end or `
    + `${data.census_date} if still running. Actual rate is what Medicaid paid per Medicaid day. Census days are `
    + "these stays' days in a bed inside the range; average daily census divides them by the range's "
    + `${data.census_range_days.toLocaleString()} days with census data. The trends below follow the same stays.` : ''

  // The trends follow the drilldown, as Historical Medicare PDPM's do: the
  // facilities under the current path, joined so the fetch reruns only when
  // they change. Texas is every facility here, so it sends no id list.
  const scopedIds = (path.length > 1 || grouping ? rows.flatMap(row => row.facilities.map(facility => facility.facility_id)) : [])
    .join(',')
  const trend = useReport<HistoricalMedicaidDaily>(
    signal => getHistoricalMedicaidDaily(startDate, endDate, dateBasis, scopedIds ? scopedIds.split(',') : [], signal),
    [startDate, endDate, dateBasis, scopedIds], Boolean(data))
  const scopeName = grouping && !path.length ? 'Custom grouping' : path[path.length - 1] ?? 'Texas'
  const trendLoading = loading || trend.loading
  const trendDays = (trend.data?.days ?? []).filter(day => day.census > 0)
  const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  const wholeMoney = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD',
    maximumFractionDigits: 0 })
  const millions = (value: number) => `$${(value / 1e6).toLocaleString(undefined,
    { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`
  const chartStatus = { loading: trendLoading, error: error ?? trend.error, onRetry: error ? retry : trend.retry }

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<OverviewRow> title={`${levels[depth]} Medicaid stays`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`historical-medicaid-${file}.csv`} />
    <AllFacilitiesModal<OverviewRow> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · Medicaid stays by ${basisLabel}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`historical-medicaid-facilities-${file}.csv`} />
    {/* Historical Medicare PDPM's trends less the neutral rate, three to a row
        on the same days, each in its own colour. */}
    <div className="report-chart-grid report-chart-grid--three-columns">
      <LineChart title="Medicaid census trending" valueLabel="Medicaid census" variant="line" height={320}
        subtitle={`${scopeName}. The Medicaid stays ${basis} from ${range}: how many were in a bed each day.`}
        items={trendDays.map(day => ({ date: day.date, value: day.census }))} {...chartStatus} />
      <LineChart title="Actual rate trending" valueLabel="Actual rate" variant="line" height={320}
        subtitle={`${scopeName}. Average daily rate Medicaid paid for those stays.`}
        items={trendDays.map(day => ({ date: day.date, value: day.actual_rates / day.census }))}
        formatValue={money} lineColor="var(--color-chart-series-senary)" {...chartStatus} />
      <LineChart title="Daily revenue trending" valueLabel="Revenue" variant="line" height={320}
        subtitle={`${scopeName}. Total revenue each day from those stays: each one in a bed that day at its daily rate.`}
        items={trendDays.map(day => ({ date: day.date, value: day.actual_rates }))}
        formatValue={wholeMoney} formatAxis={millions} lineColor="var(--color-chart-series-quinary)" {...chartStatus} />
    </div>
  </>
}

type CategoryRow = DrilldownRow<FacilityMedicaidCategories>

/** The Category breakdown tab: the same stays counted by their first code's
 * nursing function score, nursing category or NTA band. A chart segment opens
 * its stays on the Residents tab. */
export function HistoricalMedicaidCategoryBreakdown() {
  const [params, setParams] = useReportSearchParams()
  const { startDate, endDate, dateBasis, path, setPath, basis, basisLabel, range, file } = useHistoricalMedicaidSelection()
  const { data, error, loading, retry } = useReport<MedicaidCategoriesReport>(
    signal => getHistoricalMedicaidCategories(startDate, endDate, dateBasis, signal), [startDate, endDate, dateBasis])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { selected, breakdown, control } = useCategoryControl(medicaidCategories, 'Medicaid category')
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<CategoryRow>[] = [
    nameColumn<FacilityMedicaidCategories>(depth, path, setPath),
    ...categoryColumns<FacilityMedicaidCategories>(breakdown),
  ]
  const subtitle = data ? `${scopeNote} Stays ${basis} from ${range}, counted by their first assessment once it is `
    + `coded; stays not yet coded by ${data.census_date} are missing a care code and counted in no `
    + `${breakdown.name.toLowerCase()} part.` : ''
  // The Residents tab reads its opening filters from residents_* parameters.
  const openResidents = (locationPath: string[], part: string) => {
    const next = new URLSearchParams(params)
    for (const key of [...next.keys()]) {
      if (key.startsWith('residents_')) next.delete(key)
    }
    next.set('view', 'residents')
    locationPath.forEach((name, index) => next.set(`residents_${residentLocationFilters[index]}`, name))
    next.set('residents_medicaid-category', part)
    setParams(next)
  }

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
      csvFileName={`historical-medicaid-${breakdown.slug}-${file}.csv`} />
    <AllFacilitiesModal<CategoryRow> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · ${breakdown.name}, Medicaid stays by ${basisLabel}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`historical-medicaid-${breakdown.slug}-facilities-${file}.csv`} />
    <CategoryCharts<FacilityMedicaidCategories> breakdown={breakdown} rows={rows} depth={depth}
      scopeName={grouping && !path.length ? 'Custom grouping' : path[path.length - 1] ?? 'Texas'}
      unit={{ one: 'stay', many: 'stays' }}
      population={`Medicaid stays ${basis} from ${range} with a care code`}
      fileSuffix={file} loading={loading} error={error} onRetry={retry}
      onSegmentSelect={(row, partId) => {
        const part = breakdown.parts.find(([field]) => field === partId)
        if (part) openResidents(row.path, `${selected.label}: ${part[1]}`)
      }} />
  </>
}

const pageSize = 50
const twoDecimals = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const residentColumns: TableColumn<HistoricalMedicaidResident>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  // A filter only, set by a click on a Category breakdown chart segment.
  { id: 'medicaid-category', header: 'Medicaid category', filterable: true, hidden: true, value: () => '' },
  { id: 'payer-name', header: 'Payer name', filterable: true, value: row => row.payer_name },
  { id: 'medicaid-start', header: 'Medicaid start', value: row => row.start_date },
  { id: 'ard', header: 'ARD', value: row => row.ard ?? '—' },
  { id: 'active', header: 'Active', filterable: true, dataType: 'boolean', value: row => row.active },
  { id: 'medicaid-days', header: 'Medicaid days', numeric: true, value: row => row.medicaid_days },
  // The ARD is null exactly while the care code is missing, so it marks the label.
  { id: 'code', header: 'Case-mix code', filterable: true, value: row => row.case_mix_code,
    format: (_, row) => row.ard === null
      ? <span className="care-code-badge care-code-badge--missing">{row.case_mix_code}</span>
      : <span className="care-code">{row.case_mix_code}</span> },
  { id: 'average-rate', header: 'Average rate', numeric: true, value: row => row.average_rate ?? '—',
    format: value => typeof value === 'number' ? twoDecimals(value) : value },
  { id: 'total-revenue', header: 'Total revenue', numeric: true, value: row => row.total_revenue,
    format: (_, row) => twoDecimals(row.total_revenue) },
]

/** The Residents tab: every Texas Medicaid stay the Overview counts, paged,
 * sorted and filtered by the API. A new date range or date basis, or a chart
 * segment's opening filters, start the table over on its first page. */
export function HistoricalMedicaidResidents() {
  const [params] = useReportSearchParams()
  const { startDate, endDate, dateBasis } = useHistoricalMedicaidSelection()
  const initialFilters: Record<string, string[]> = {}
  for (const [key, value] of params) {
    if (key.startsWith('residents_')) (initialFilters[key.slice('residents_'.length)] ??= []).push(value)
  }
  return <HistoricalMedicaidResidentsTable key={`${startDate}|${endDate}|${dateBasis}|${JSON.stringify(initialFilters)}`}
    startDate={startDate} endDate={endDate} dateBasis={dateBasis} initialFilters={initialFilters} />
}

function HistoricalMedicaidResidentsTable({ startDate, endDate, dateBasis, initialFilters }: {
  startDate: string; endDate: string; dateBasis: 'start' | 'ard'; initialFilters: Record<string, string[]>
}) {
  const [query, setQuery] = useState<MedicareResidentsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: HistoricalMedicaidResident[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: MedicareResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    void getHistoricalMedicaidResidents(startDate, endDate, dateBasis, pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, dateBasis, pageIndex, query, requestKey])
  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error, onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  const basis = dateBasis === 'ard' ? 'whose first assessment ARD falls' : 'that started'
  return <Table<HistoricalMedicaidResident> {...status}
    title="Medicaid stays"
    subtitle={`${scopeNote} Every stay ${basis} from ${startDate} to ${endDate}, the stays the Overview counts. `
      + `Payer name shows the plan. Medicaid days run through the stay's end, or ${censusDate || 'the census day'} `
      + 'while it is active. ARD is the first assessment\'s reference date and the code its two letters, nursing '
      + 'and NTA; until it is coded the care code is missing and the ARD blank. Revenue is every day of the stay '
      + 'at its Medicaid rate; the average rate is revenue per Medicaid day.'}
    columns={residentColumns} rows={result?.items ?? []} getRowKey={row => row.payer_stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'historical-medicaid-residents', startDate, endDate,
      endpoint: historicalMedicaidResidentFilterOptions(dateBasis) }}
    onQueryChange={onQueryChange} totalRows={result?.total} initialFilters={initialFilters}
    emptyMessage="No stays match these filters."
    csvFileName={`historical-medicaid-residents-${startDate}-to-${endDate}-by-${dateBasis}.csv`}
    onExport={() => downloadHistoricalMedicaidResidents(startDate, endDate, dateBasis, query)}
    footer={<nav aria-label="Stay pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} stays`
          : error ? 'Pagination unavailable' : 'Loading stays…'}
      </span>
      <div className="report-table__pagination-actions">
        {[
          { label: 'First page', symbol: '«', index: 0, disabled: pageIndex === 0 },
          { label: 'Previous page', symbol: '‹', index: pageIndex - 1, disabled: pageIndex === 0 },
          { label: 'Next page', symbol: '›', index: pageIndex + 1, disabled: pageIndex + 1 >= pageCount },
          { label: 'Last page', symbol: '»', index: pageCount - 1, disabled: pageIndex + 1 >= pageCount },
        ].map(({ label, symbol, index, disabled }) => <button key={label} type="button"
          className="report-table__pagination-arrow" aria-label={label} title={label}
          disabled={status.loading || !!error || disabled} onClick={() => setPage({ queryKey, index })}>
          <span aria-hidden="true">{symbol}</span>
        </button>)}
      </div>
    </nav>}
  />
}
