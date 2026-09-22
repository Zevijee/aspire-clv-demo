import dayjs from 'dayjs'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DataState } from '../../../shared/components/DataState'
import { DrilldownNavigation, type DrilldownBreadcrumb } from '../../../shared/components/DrilldownNavigation'
import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { groupTrendPeriods, trendBlockSize } from '../../../shared/utils/trendPeriods'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { useDischargesOverview } from '../hooks/useDischargesOverview'
import { payerCode, payerLabel } from '../api/admissionsOverview'
import { dischargeSelectionParameters, type DischargeLocation, type DischargeSelection } from '../api/dischargesOverview'
import { getLocationLevel } from '../utils/admissionsOverviewFilters'
import { dischargeLogsParams, type DischargeCount } from '../utils/dischargeLogsFilters'
import type { DrilldownScope } from '../utils/admissionsDrilldown'

export type { DischargeSelection } from '../api/dischargesOverview'

type Row = DischargeLocation & { prior: number | null; change: number | null; isTotal?: boolean }

const averageFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

export function DischargesOverview({ selection, onChange }: {
  selection: DischargeSelection
  onChange: (selection: DischargeSelection) => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaults.startDate
  const endDate = searchParams.get('end_date') ?? defaults.endDate
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const priorEnd = dayjs(startDate).subtract(1, 'day').format('YYYY-MM-DD')
  const priorStart = dayjs(startDate).subtract(days, 'day').format('YYYY-MM-DD')
  const { scope, destinations } = selection
  const payers = selection.payers.map(payerCode)
  const customLevel = selection.groupBy ?? getLocationLevel(selection.locations ?? [])
  const level = scope === null ? customLevel ?? 'state'
    : scope.portfolio === undefined ? 'portfolio'
    : scope.region === undefined ? 'region' : 'facility'
  const detail = scope?.facility !== undefined
  const references = useAdmissionsReferences()
  const parameters = references.data
    ? dischargeSelectionParameters(selection, references.data, level).toString() : null
  // Two independent requests: this period and the one immediately before it. A
  // failed prior period degrades the comparison columns instead of the report.
  const current = useDischargesOverview(startDate, endDate, parameters)
  const previous = useDischargesOverview(priorStart, priorEnd, parameters)
  const status = {
    loading: references.loading || current.loading,
    error: references.error ?? current.error,
    onRetry: references.error ? references.onRetry : current.onRetry,
  }
  const priorRows = new Map(previous.data?.locations.map(row => [row.id, row.discharges]))
  const rows: Row[] = (current.data?.locations ?? []).map(row => {
    const prior = previous.data ? priorRows.get(row.id) ?? 0 : null
    return { ...row, prior, change: prior === null ? null : row.discharges - prior }
  })
  const scopeName = scope?.facility ?? scope?.region ?? scope?.portfolio ?? scope?.state ?? 'All selected locations'
  const navigate = (next: DrilldownScope) => onChange({ ...selection, scope: next })
  const setPayers = (values: string[]) => onChange({ ...selection, payers: values })
  const setDestinations = (values: string[]) => onChange({ ...selection, destinations: values })
  const breadcrumbs: DrilldownBreadcrumb[] = []
  if (scope) {
    breadcrumbs.push({ id: 'state', label: scope.state, onSelect: () => navigate({ state: scope.state }) })
    if (scope.portfolio !== undefined) breadcrumbs.push({ id: 'portfolio', label: scope.portfolio,
      onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio }) })
    if (scope.region !== undefined) breadcrumbs.push({ id: 'region', label: scope.region,
      onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio, region: scope.region }) })
    if (scope.facility !== undefined) breadcrumbs.push({ id: 'facility', label: scope.facility })
  }
  function drillInto(row: Row) {
    const path = Object.fromEntries(row.path.map(part => [part.level, part.name]))
    navigate({ state: path.state, ...(path.portfolio ? { portfolio: path.portfolio } : {}),
      ...(path.region ? { region: path.region } : {}), ...(path.facility ? { facility: path.facility } : {}) })
  }
  function openLogs(row: Row, count: DischargeCount) {
    setSearchParams(dischargeLogsParams(searchParams, row.facility_ids,
      { payers, destinations }, count, startDate, endDate))
  }
  // Footer totals re-add the sums, then divide once. Averaging the visible rows'
  // averages would weight a 3-discharge facility like a 300-discharge one.
  function total(visible: Row[]): Row | null {
    if (visible.length < 2) return null
    const sum = (pick: (row: Row) => number) => visible.reduce((value, row) => value + pick(row), 0)
    const discharges = sum(row => row.discharges)
    const stayDays = sum(row => row.length_of_stay_days)
    const prior = visible.some(row => row.prior === null) ? null : sum(row => row.prior!)
    return { id: 'total', name: 'Total', level, path: [], isTotal: true, discharges,
      prior, change: prior === null ? null : discharges - prior,
      hospital_transfers: sum(row => row.hospital_transfers),
      ama_discharges: sum(row => row.ama_discharges),
      deceased_discharges: sum(row => row.deceased_discharges),
      length_of_stay_days: stayDays,
      average_length_of_stay: discharges ? stayDays / discharges : 0,
      average_per_day: discharges / days,
      facility_ids: [...new Set(visible.flatMap(row => row.facility_ids))] }
  }
  const countColumn = (id: DischargeCount, header: string, pick: (row: Row) => number): TableColumn<Row> => ({
    id, header, numeric: true, initialSortDirection: 'descending', value: row => pick(row),
    format: (value, row) => pick(row) === 0 ? '0' : <button type="button"
      className="admissions-explorer__drill admissions-explorer__drill--count"
      aria-label={`View ${row.name} ${header.toLowerCase()} in Logs`}
      onClick={() => openLogs(row, id)}>{value.toLocaleString()}</button>,
  })
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: level[0].toUpperCase() + level.slice(1), isRowHeader: true, value: row => row.name,
      format: (_, row) => {
        const name = <span className="admissions-explorer__entity"><strong>{row.name}</strong></span>
        return row.isTotal || detail ? name
          : <button type="button" className="admissions-explorer__drill" onClick={() => drillInto(row)}>{name}</button>
      } },
    countColumn('total', 'Total discharges', row => row.discharges),
    { id: 'average-los', header: 'Average LOS (days)', numeric: true,
      value: row => row.average_length_of_stay,
      format: value => typeof value === 'number' ? averageFormat.format(value) : value },
    { id: 'prior', header: 'Prior-period discharges', numeric: true, value: row => row.prior ?? '—',
      format: value => value.toLocaleString() },
    { id: 'change', header: 'Discharges vs prior', numeric: true, value: row => row.change ?? '—',
      change: { favorable: 'decrease' } },
    countColumn('ama', 'AMA discharges', row => row.ama_discharges),
    countColumn('hospitalTransfers', 'Hospital transfers', row => row.hospital_transfers),
  ]
  const blockSize = trendBlockSize(startDate, endDate)
  const trend = groupTrendPeriods(
    (current.data?.daily ?? []).map(row => ({ date: row.date, value: row.discharges })), startDate, blockSize)
  const heading = level[0].toUpperCase() + level.slice(1)
  return <>
    <DrilldownNavigation ariaLabel="Discharges drill-down" items={breadcrumbs}
      locationView={{ groupBy: customLevel ?? 'state', selectedCount: selection.locations?.length ?? 0,
        selectionLevel: getLocationLevel(selection.locations ?? []), onReturn: () => navigate(null),
        onClear: () => onChange({ ...selection, scope: null, locations: [], groupBy: 'state' }) }}
      activeFilters={[...(payers.length ? ['payer'] : []), ...(destinations.length ? ['destination'] : [])]}
      onClearFilter={filter => { if (filter === 'payer') setPayers([]); if (filter === 'destination') setDestinations([]) }} />
    {previous.error && !status.error && <DataState label="Prior period"
      error={`Prior period: ${previous.error}`} onRetry={previous.onRetry} />}
    <Table {...status} key={JSON.stringify([scope, selection.locations, selection.groupBy])}
      columns={columns} rows={rows} getRowKey={row => row.id} getFooterRow={total}
      initialSort={{ columnId: 'total', direction: 'descending' }}
      title={`${heading} Discharge Metrics`}
      subtitle={`${scopeName} · Compared with the immediately preceding period of equal length`}
      csvFileName={`discharges-${level}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No locations match this view." />
    <div className="admissions-dashboard">
      <BarChartRanking {...status} title="Discharges by Destination Type"
        subtitle="Click destinations to filter the report"
        categoryLabel="Destination type" valueLabel="Discharges"
        items={(current.data?.by_destination ?? []).map(row => ({ label: row.destination_type, value: row.discharges }))
          .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))}
        selectedLabels={destinations} onClear={() => setDestinations([])}
        onSelect={value => setDestinations(destinations.includes(value)
          ? destinations.filter(item => item !== value) : [...destinations, value])} />
      <DonutChart {...status} title="Discharges by Payer Type" subtitle="Click payers to filter the report"
        items={(current.data?.by_payer ?? []).map(row => ({ label: payerLabel(row.payer_type), value: row.discharges }))}
        selectedLabels={payers.map(payerLabel)} onClear={() => setPayers([])} onSelect={label => {
          const value = payerCode(label)
          setPayers(payers.includes(value) ? payers.filter(item => item !== value) : [...payers, value])
        }} />
    </div>
    <LineChart {...status} items={trend} title={blockSize === 1 ? 'Daily Discharge Trend' : 'Discharges trend'}
      valueLabel="Discharges" variant="bar" barColor="var(--color-table-change-adverse)" height={400}
      subtitle={blockSize === 1 ? 'Total discharges each day'
        : `Total discharges per ${blockSize}-day period. The tooltip shows the exact dates and day count.`} />
  </>
}
