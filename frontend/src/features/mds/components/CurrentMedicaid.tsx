import { useCallback, useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { LocationName } from '../../../shared/components/LocationName'
import { LookbackCards, type LookbackMeasure } from '../../../shared/components/LookbackCards'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import {
  downloadMedicaidResidents, getMedicaidLookback, getMedicaidOverview, getMedicaidResidents,
  medicaidResidentFilterOptions, type FacilityMedicaid, type FacilityMedicaidLookback, type MedicaidLookbackReport,
  type MedicaidOverviewReport, type MedicaidResident, type MedicareResidentsQuery,
} from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../../../shared/utils/locationDrilldown'
import { LocationNavigation, locationColumn as nameColumn } from '../../../shared/components/LocationNavigation'
import { CategoryCharts, categoryColumns, useCategoryControl, type CategoryId } from './CategoryBreakdown'

type Row = DrilldownRow<FacilityMedicaid>
type LookbackRow = DrilldownRow<FacilityMedicaidLookback>
// Texas pays Medicaid on the nursing and NTA components alone, so its code has
// only these categories.
export const medicaidCategories: CategoryId[] = ['nursing', 'nursing-category', 'nta']
// The Residents tab's filter for each level of a location path, in path order.
export const residentLocationFilters = ['state', 'portfolio', 'region', 'facility']
export const scopeNote = 'Texas Medicaid residents, whose Medicaid pays on the PDPM nursing and NTA components; Florida '
  + 'and Pennsylvania use other systems and are not included.'

const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
const shortDate = (value: string) => new Date(`${value}T00:00:00`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

// Texas is the only state in this report, so a state level would be one row:
// the drilldown starts inside it, at its portfolios.
export const homePath = ['TX']

/** The drilldown location in the URL (one drill= per level, in order), shared
 * by the Overview and Category breakdown tabs so switching keeps it. With none
 * in the URL it is Texas. */
export function useDrillPath() {
  const [params, setParams] = useReportSearchParams()
  const drilled = params.getAll('drill')
  const path = drilled.length ? drilled : homePath
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  return { path, setPath }
}

/** The census-day report, fetched again on a retry. */
function useMedicaidOverview() {
  const [data, setData] = useState<MedicaidOverviewReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getMedicaidOverview(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])
  return { data, error, loading: !data && !error, retry: () => setRetry(value => value + 1) }
}

type Summed = 'residents' | 'actual_rates' | 'resident_days' | 'no_score' | 'no_score_days'
const sum = (row: Row, field: Summed) => row.facilities.reduce((total, facility) => total + facility[field], 0)
// Sums at this scope divided once: never an average of facility averages.
function metric(row: Row, field: string): number | null {
  const residents = sum(row, 'residents')
  if (field === 'actual_rate') return residents > 0 ? sum(row, 'actual_rates') / residents : null
  if (field === 'los') return residents > 0 ? sum(row, 'resident_days') / residents : null
  if (field === 'missing_los') {
    const missing = sum(row, 'no_score')
    return missing > 0 ? sum(row, 'no_score_days') / missing : null
  }
  return sum(row, field as Summed)
}
// No neutral rate: Medicaid pays its own rate, which no case-mix-neutral rate
// compares with here.
const metrics: [id: string, header: string, kind: 'count' | 'rate' | 'days'][] = [
  ['residents', 'Census', 'count'], ['no_score', 'Missing care code', 'count'],
  ['missing_los', 'Avg. LOS, missing care code', 'days'], ['actual_rate', 'Rate', 'rate'],
  ['los', 'Avg. length of stay', 'days'],
]
function formatMetric(value: number | string, kind: 'count' | 'rate' | 'days') {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return money(value)
  const digits = kind === 'days' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** The Overview tab: today's Texas Medicaid residents by location, and the same
 * scope's census and rate against earlier days and averages. */
export function MedicaidOverview() {
  const { path, setPath } = useDrillPath()
  const { data, error, loading, retry } = useMedicaidOverview()
  const [past, setPast] = useState<MedicaidLookbackReport | null>(null)
  const [pastError, setPastError] = useState<string | null>(null)
  const [pastRetry, setPastRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    // Apart, so the look-back loading never holds up today's table.
    const controller = new AbortController()
    setPastError(null)
    getMedicaidLookback(controller.signal)
      .then(body => { if (!controller.signal.aborted) setPast(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setPastError(failure.message) })
    return () => controller.abort()
  }, [pastRetry])

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    nameColumn<FacilityMedicaid>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—', format: value => formatMetric(value, kind),
    })),
  ]
  const subtitle = data ? `${scopeNote} In a bed on ${data.census_date}. Missing care code is residents not yet `
    + 'assessed and coded in the first days of their Medicaid stay. Rate is what Medicaid pays per day.' : ''

  // The look-back follows the same drilldown: one card, the current scope.
  const { rows: pastRows } = groupByLocation(past?.items ?? [], path, grouping)
  const scopeRow: LookbackRow = { key: 'scope', name: path.length ? path[path.length - 1]
    : grouping ? 'Custom grouping' : 'All locations', path, facilities: pastRows.flatMap(row => row.facilities),
    isTotal: true }
  // The periods after today: single earlier days, then averages.
  const earlier = (past?.periods ?? []).filter(period => period.key !== 'today')
  // A period's value at a scope, summed and divided once: residents per day,
  // the rate per resident-day.
  const periodValue = (row: LookbackRow, id: string, key: string, days: number) => {
    let residentDays = 0, actual = 0
    for (const facility of row.facilities) {
      const totals = facility.periods[key]
      if (!totals) return null
      residentDays += totals.resident_days
      actual += totals.actual_rates
    }
    if (id === 'residents') return days > 0 ? residentDays / days : null
    return residentDays > 0 ? actual / residentDays : null
  }
  const lookbackMeasures = ([['residents', 'Census'], ['actual', 'Rate']] as const)
    .map(([id, label]): LookbackMeasure<LookbackRow> => ({
      id, label, favorable: 'increase',
      value: (row, key) => key === null ? periodValue(row, id, 'today', 1)
        : periodValue(row, id, key, earlier.find(period => period.key === key)?.days ?? 0),
      format: (value, average) => id !== 'residents' ? money(value) : value.toLocaleString(undefined,
        { minimumFractionDigits: average ? 1 : 0, maximumFractionDigits: average ? 1 : 0 }),
      step: id === 'residents' ? 0.1 : 0.01,
    }))

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} census`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicaid-${data?.census_date ?? 'today'}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={data ? `All facilities · census on ${data.census_date}` : 'All facilities'} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`current-medicaid-facilities-${data?.census_date ?? 'today'}.csv`} />
    <LookbackCards<LookbackRow> scope={scopeRow} measures={lookbackMeasures}
      currentLabel="Today" currentTitle={past ? shortDate(past.census_date) : undefined}
      periods={earlier.map(({ key, label, start, end, average }) =>
        ({ key, label, title: start === end ? shortDate(start) : `${shortDate(start)} to ${shortDate(end)}`, average }))}
      title="Historical look-back"
      csvFileName={`current-medicaid-lookback-${past?.census_date ?? 'today'}.csv`}
      loading={!past && !pastError} error={pastError} onRetry={() => setPastRetry(value => value + 1)} />
  </>
}

/** The Category breakdown tab: the coded residents by nursing function score,
 * nursing category or NTA band. A chart segment opens its residents. */
export function MedicaidCategoryBreakdown() {
  const [params, setParams] = useReportSearchParams()
  const { path, setPath } = useDrillPath()
  const { data, error, loading, retry } = useMedicaidOverview()
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { selected, breakdown, control } = useCategoryControl(medicaidCategories, 'Medicaid category')
  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    nameColumn<FacilityMedicaid>(depth, path, setPath),
    ...categoryColumns<FacilityMedicaid>(breakdown),
  ]
  const day = data?.census_date ?? 'today'
  const subtitle = data ? `${scopeNote} In a bed on ${data.census_date}. Residents not yet coded are missing a care `
    + `code and counted in no ${breakdown.name.toLowerCase()} part.` : ''
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
    <DrilldownTable<Row> title={`${breakdown.name} by ${levels[depth].toLowerCase()}`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicaid-${breakdown.slug}-${day}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · ${breakdown.name}, census on ${day}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retry}
      csvFileName={`current-medicaid-${breakdown.slug}-facilities-${day}.csv`} />
    <CategoryCharts<FacilityMedicaid> breakdown={breakdown} rows={rows} depth={depth}
      scopeName={path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'}
      unit={{ one: 'resident', many: 'residents' }}
      population={`Medicaid residents with a care code on ${data?.census_date ?? ''}`}
      fileSuffix={day} loading={loading} error={error} onRetry={retry}
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
const residentColumns: TableColumn<MedicaidResident>[] = [
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
  { id: 'admission-date', header: 'Admission date', value: row => row.admission_date },
  { id: 'los', header: 'Length of stay', numeric: true, value: row => row.length_of_stay },
  { id: 'ard', header: 'ARD', value: row => row.ard ?? '—' },
  // The ARD is null exactly while the care code is missing, so it marks the label.
  { id: 'code', header: 'Case-mix code', filterable: true, value: row => row.case_mix_code,
    format: (_, row) => row.ard === null
      ? <span className="care-code-badge care-code-badge--missing">{row.case_mix_code}</span>
      : <span className="care-code">{row.case_mix_code}</span> },
  { id: 'daily-rate', header: 'Daily rate', numeric: true, value: row => row.daily_rate,
    format: (_, row) => twoDecimals(row.daily_rate) },
  { id: 'total-revenue', header: 'Total revenue', numeric: true, value: row => row.total_revenue,
    format: (_, row) => twoDecimals(row.total_revenue) },
]

/** The Residents tab: every Texas Medicaid resident on the census day, paged,
 * sorted and filtered by the API. Opening filters come from residents_*
 * parameters, set when a chart segment is clicked. */
export function MedicaidResidents() {
  const [params] = useReportSearchParams()
  const initialFilters: Record<string, string[]> = {}
  for (const [key, value] of params) {
    if (key.startsWith('residents_')) (initialFilters[key.slice('residents_'.length)] ??= []).push(value)
  }
  return <MedicaidResidentsTable key={JSON.stringify(initialFilters)} initialFilters={initialFilters} />
}

function MedicaidResidentsTable({ initialFilters }: { initialFilters: Record<string, string[]> }) {
  const [query, setQuery] = useState<MedicareResidentsQuery>({ filters: initialFilters, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: MedicaidResident[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [censusDate, setCensusDate] = useState('')
  const onQueryChange = useCallback((next: MedicareResidentsQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    void getMedicaidResidents(pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setResponse({ key: requestKey, items: data.items, total: data.total })
        setCensusDate(data.census_date)
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [pageIndex, query, requestKey])
  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error, onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <Table<MedicaidResident> {...status}
    title="Medicaid residents"
    subtitle={`${scopeNote}${censusDate ? ` In a bed on ${censusDate}.` : ''} Payer name shows the plan. Length of stay `
      + 'is days since admission. The case-mix code is two letters, nursing and NTA; until the assessment is coded the '
      + 'care code is missing and the ARD blank. Total revenue is Medicaid revenue on this payer to date.'}
    columns={residentColumns} rows={result?.items ?? []} getRowKey={row => row.payer_stay_id}
    initialSort={{ columnId: 'resident', direction: 'ascending' }}
    internalScroll stickyFirstColumn searchable serverSide clearableFilters
    filterSource={{ id: 'medicaid-residents', startDate: censusDate, endDate: censusDate,
      endpoint: medicaidResidentFilterOptions }}
    onQueryChange={onQueryChange} totalRows={result?.total} initialFilters={initialFilters}
    emptyMessage="No residents match these filters."
    csvFileName={`current-medicaid-residents-${censusDate || 'today'}.csv`}
    onExport={() => downloadMedicaidResidents(query, censusDate || 'today')}
    footer={<nav aria-label="Resident pagination" className="report-table__pagination">
      <span className="report-table__pagination-summary" role="status" aria-live="polite">
        {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} residents`
          : error ? 'Pagination unavailable' : 'Loading residents…'}
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
