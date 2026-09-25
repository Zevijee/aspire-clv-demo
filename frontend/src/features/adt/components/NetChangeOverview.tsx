import { useMemo } from 'react'
import { NetChangePayerFilter } from './NetChangePayerFilter'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownNavigation, type DrilldownBreadcrumb } from '../../../shared/components/DrilldownNavigation'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { locationPlace } from '../utils/locationPlace'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { useNetChangeOverview } from '../hooks/useNetChangeOverview'
import { payerLabel } from '../api/admissionsOverview'
import { netChangeParameters, type NetChangeLocation, type NetChangeSelection } from '../api/netChangeOverview'
import { getLocationLevel, locationLevels } from '../utils/admissionsOverviewFilters'
import { NetChangeDailyTrend } from './NetChangeDailyTrend'
import type { DrilldownScope } from '../utils/admissionsDrilldown'

type Row = NetChangeLocation & { isTotal?: boolean }

export function NetChangeOverview() {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate

  const payerKey = JSON.stringify([...new Set(params.getAll('net_payer'))].sort())
  const selectedPayers = useMemo(() => JSON.parse(payerKey) as string[], [payerKey])
  const scopeKey = JSON.stringify(params.getAll('net_scope').slice(0, 4))
  const path = useMemo(() => JSON.parse(scopeKey) as string[], [scopeKey])
  const locationKey = JSON.stringify(params.getAll('net_location'))
  const locations = useMemo(() => JSON.parse(locationKey) as string[], [locationKey])
  const requested = params.get('net_level')
  const customLevel = locationLevels.find(value => value === requested)
    ?? getLocationLevel(locations) ?? 'state'

  const scope: DrilldownScope = path.length
    ? { state: path[0], portfolio: path[1], region: path[2], facility: path[3] } : null
  const level = scope === null ? customLevel
    : scope.portfolio === undefined ? 'portfolio'
    : scope.region === undefined ? 'region' : 'facility'
  const detail = scope?.facility !== undefined
  const selection: NetChangeSelection = { scope, payers: selectedPayers, locations, groupBy: customLevel }

  const references = useAdmissionsReferences()
  const parameters = references.data
    ? netChangeParameters(selection, references.data, level).toString() : null
  const current = useNetChangeOverview(startDate, endDate, parameters)
  // Show all facilities: the same report at facility grain, fetched only while
  // open. Filters and any custom location selection apply; the drilldown does not.
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const allParameters = showFacilities && references.data
    ? netChangeParameters({ ...selection, scope: null }, references.data, 'facility').toString() : null
  const allCurrent = useNetChangeOverview(startDate, endDate, allParameters)
  const status = {
    loading: references.loading || current.loading,
    error: references.error ?? current.error,
    onRetry: references.error ? references.onRetry : current.onRetry,
  }
  const days = current.data?.range.days ?? 1
  const rows: Row[] = current.data?.locations ?? []

  function setPath(next: string[]) {
    const params2 = new URLSearchParams(params)
    params2.delete('net_scope')
    next.forEach(part => params2.append('net_scope', part))
    setParams(params2)
  }
  function setPayer(payer?: string) {
    const next = new URLSearchParams(params)
    const payers = payer
      ? selectedPayers.includes(payer)
        ? selectedPayers.filter(value => value !== payer) : [...selectedPayers, payer]
      : []
    next.delete('net_payer')
    payers.forEach(value => next.append('net_payer', value))
    setParams(next)
  }
  const breadcrumbs: DrilldownBreadcrumb[] = path.map((name, index) => ({
    id: JSON.stringify(path.slice(0, index + 1)), label: name,
    onSelect: () => setPath(path.slice(0, index + 1)),
  }))

  // Census is a level, so the footer takes opening from the earliest row and
  // closing from the latest rather than summing either across the period.
  function total(visible: Row[]): Row | null {
    if (visible.length < 2) return null
    const sum = (pick: (row: Row) => number) => visible.reduce((value, row) => value + pick(row), 0)
    const opening = sum(row => row.opening_census)
    const closing = sum(row => row.closing_census)
    return { id: 'total', name: 'Total', level, path: [], isTotal: true,
      facility_ids: [...new Set(visible.flatMap(row => row.facility_ids))],
      facility_count: sum(row => row.facility_count),
      opening_census: opening, closing_census: closing,
      admissions: sum(row => row.admissions), discharges: sum(row => row.discharges),
      payer_changes_in: sum(row => row.payer_changes_in),
      payer_changes_out: sum(row => row.payer_changes_out),
      net_change: closing - opening, average_per_day: (closing - opening) / days }
  }
  const number = (value: string | number) =>
    typeof value === 'number' ? value.toLocaleString() : value
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: level[0].toUpperCase() + level.slice(1), isRowHeader: true,
      value: row => row.name,
      format: (_, row) => row.isTotal || detail ? row.name
        : <button type="button" className="drilldown-table__link"
            onClick={() => setPath(row.path.map(part => part.name))}>{row.name}</button> },
    { id: 'net_change', header: 'Net change', numeric: true, value: row => row.net_change,
      change: { favorable: 'increase' } },
    ...(['opening_census', 'admissions', 'discharges', 'closing_census'] as const)
      .map((id): TableColumn<Row> => ({
        id, header: { opening_census: 'Open census', closing_census: 'Close census',
          admissions: 'Admissions', discharges: 'Discharges' }[id],
        numeric: true, value: row => row[id], format: number })),
    // Only meaningful with a payer filter. Unfiltered, every move is both out of
    // one type and into another, so the two columns are equal and cancel.
    ...(selectedPayers.length ? (['payer_changes_in', 'payer_changes_out'] as const)
      .map((id): TableColumn<Row> => ({
        id, header: id === 'payer_changes_in' ? 'Payer in' : 'Payer out',
        numeric: true, value: row => row[id], format: number })) : []),
    // Payer-type changes in this scope. Unfiltered, moves in equal moves out, so
    // either side is the count of changes; with a filter it is moves into the
    // selected types.
    { id: 'payer_changes', header: 'Payer changes', numeric: true,
      value: row => row.payer_changes_in, format: number },
  ]
  return <>
    <DrilldownNavigation ariaLabel="Net change drill-down" items={breadcrumbs}
      locationView={{ groupBy: customLevel, selectedCount: locations.length,
        selectionLevel: getLocationLevel(locations),
        onReturn: () => setPath([]), onClear: () => {
          const next = new URLSearchParams(params)
          for (const key of ['net_scope', 'net_location', 'net_level']) next.delete(key)
          setParams(next)
        } }}
      activeFilters={selectedPayers.map(payerLabel)}
      onClearFilter={label => {
        const payer = selectedPayers.find(value => payerLabel(value) === label)
        if (payer) setPayer(payer)
      }} />
    <Table {...status} key={JSON.stringify([scopeKey, locationKey, customLevel])}
      title={`${level[0].toUpperCase() + level.slice(1)} net change`}
      subtitle={`Net change is close census minus open census.${selectedPayers.length ? ' Payer in and out count moves between payer types.' : ''}`}
      columns={columns} rows={rows} getRowKey={row => row.id} getFooterRow={total}
      stickyFirstColumn retainRowsWhileLoading
      initialSort={{ columnId: 'net_change', direction: 'descending' }}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      csvFileName={`net-change-${level}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No locations match this view." />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      filters={<NetChangePayerFilter />}
      title={`All facilities · net change, ${startDate} to ${endDate}`}
      subtitle="Every facility in the selection, with the same payer filter. Net change is close census minus open census."
      rows={allCurrent.data?.locations ?? []} columns={columns.slice(1)} getRowKey={row => row.id}
      getName={row => row.name} getPath={row => locationPlace(row.path)}
      loading={references.loading || allCurrent.loading} error={references.error ?? allCurrent.error}
      onRetry={allCurrent.onRetry}
      csvFileName={`net-change-facilities-${startDate}-to-${endDate}.csv`} />
    <NetChangeDailyTrend daily={current.data?.daily ?? []} {...status}
      startDate={startDate} endDate={endDate} hasPayers={selectedPayers.length > 0} />
  </>
}
