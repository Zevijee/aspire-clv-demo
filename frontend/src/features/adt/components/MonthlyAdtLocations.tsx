import { useEffect, useState } from 'react'
import { MonthlyAdtFilters } from './MonthlyAdtFilters'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import type { TableColumn } from '../../../shared/components/Table'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { groupingPaths, locationLevels, useLocationView } from '../../../shared/customGrouping'
import {
  getMonthlyLocations, monthlyFilter, monthlyParameters,
  type MonthlyLocation, type MonthlyLocationItem, type MonthlyTab,
} from '../api/monthlyAdt'

type Metric = 'admissions' | 'discharges' | 'net_change'
type Result = { locations: MonthlyLocation[]; items: Record<Metric, MonthlyLocationItem[]> }
type Row = { key: string; name: string; months: Record<Metric, number[]>; isTotal?: boolean
  // The location's full name path, on drilldown rows: drilling sets it.
  path?: string[]
  // State, portfolio and region, on facility rows only.
  place?: readonly [string, string, string] }
const levels = ['state', 'portfolio', 'region', 'facility_name'] as const
const labels = ['State', 'Portfolio', 'Region', 'Facility']
// Each measure, the view that answers it, and its column group's label. Each
// view reads its own monthly table, as the charts below the table do.
const measures: { metric: Metric; tab: MonthlyTab; label: string }[] = [
  { metric: 'admissions', tab: 'admissions', label: 'admissions' },
  { metric: 'discharges', tab: 'discharges', label: 'discharges' },
  { metric: 'net_change', tab: 'net-change', label: 'net change' },
]

/** Monthly ADT by location: for admissions, discharges and net change, each
 * location's average per month and its highest and lowest month, drilled from
 * state to facility. Admissions follow the Coming from filter and discharges
 * the Going to filter, as their charts do; net change reads census, which
 * neither divides. */
export function MonthlyAdtLocations({ startDate, endDate, path, setPath }: {
  startDate: string; endDate: string
  path: string[]; setPath: (path: string[]) => void
}) {
  const [params] = useSearchParams()
  const [retry, setRetry] = useState(0)
  const references = useAdmissionsReferences()
  const queries = references.data ? measures.map(({ tab }) => {
    const filter = monthlyFilter[tab as keyof typeof monthlyFilter]
    return monthlyParameters({ references: references.data!, payers: params.getAll('monthly_payer'),
      path: [], filter, values: filter ? params.getAll(filter.search) : [] }).toString()
  }) : null
  const key = JSON.stringify([queries, startDate, endDate, retry])
  const [response, setResponse] = useState<{ key: string; data?: Result; error?: string } | null>(null)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  const { grouping, locationView } = useLocationView(() => setPath([]))
  useEffect(() => {
    if (queries === null) return
    const controller = new AbortController()
    void Promise.all(measures.map(({ tab }, index) =>
      getMonthlyLocations(tab, startDate, endDate, queries[index], controller.signal)))
      .then(([admissions, discharges, netChange]) => {
        if (controller.signal.aborted) return
        setResponse({ key, data: { locations: admissions.locations,
          items: { admissions: admissions.items, discharges: discharges.items, net_change: netChange.items } } })
      }, (error: Error) => { if (!controller.signal.aborted) setResponse({ key, error: error.message }) })
    return () => controller.abort()
    // queries is a new array each render; key names everything it reads.
  }, [key])
  const result = response?.key === key ? response : null
  const months: string[] = []
  for (let month = dayjs(startDate).startOf('month'); !month.isAfter(dayjs(endDate), 'month'); month = month.add(1, 'month')) {
    months.push(month.format('YYYY-MM'))
  }
  const empty = () => ({ admissions: months.map(() => 0), discharges: months.map(() => 0), net_change: months.map(() => 0) })
  const groups = new Map<string, Row>()
  const facilityGroups = new Map<string, Row>()
  // At the top, a custom grouping's locations are the rows; below it, the
  // level under the path.
  const custom = grouping && !path.length ? groupingPaths(grouping) : null
  const depth = custom ? locationLevels.indexOf(grouping!.level) : Math.min(path.length, 3)
  for (const location of result?.data?.locations ?? []) {
    const place = levels.map(level => location[level])
    const under = (prefix: string[]) => prefix.every((part, index) => place[index] === part)
    const rowPath = custom ? custom.find(under) : under(path) ? place.slice(0, depth + 1) : undefined
    if (!rowPath) continue
    const rowKey = JSON.stringify(rowPath)
    let row = groups.get(rowKey)
    if (!row) { row = { key: rowKey, name: rowPath[rowPath.length - 1], path: rowPath, months: empty() }; groups.set(rowKey, row) }
    facilityGroups.set(location.facility_id, row)
  }
  // Every facility, whatever the drilldown shows, for Show all facilities.
  const facilityRows = new Map<string, Row>((result?.data?.locations ?? []).map(location => [location.facility_id, {
    key: location.facility_id, name: location.facility_name, months: empty(),
    place: [location.state, location.portfolio, location.region] as const }]))
  for (const { metric } of measures) {
    for (const item of result?.data?.items[metric] ?? []) {
      const index = months.indexOf(item.month)
      if (index < 0) continue
      const row = facilityGroups.get(item.facility_id)
      if (row) row.months[metric][index] += Number(item[metric])
      const facility = facilityRows.get(item.facility_id)
      if (facility) facility.months[metric][index] += Number(item[metric])
    }
  }
  const extreme = (row: Row, metric: Metric, high: boolean) => (high ? Math.max : Math.min)(...row.months[metric])
  const formatValue = (metric: Metric, value: number) => value.toLocaleString(undefined, {
    maximumFractionDigits: 1, signDisplay: metric === 'net_change' ? 'exceptZero' : 'auto',
  })
  // The value first, its month after it as a small muted tag.
  const extremeLabel = (row: Row, metric: Metric, high: boolean) => {
    const value = extreme(row, metric, high)
    const matches = row.months[metric].flatMap((count, index) => count === value ? [dayjs(`${months[index]}-01`).format('MMM YYYY')] : [])
    return <span className="report-table__value-with-tag" title={matches.join(', ')}>{formatValue(metric, value)}
      <span className="report-table__tag">{matches[0]}{matches.length > 1 ? ` +${matches.length - 1}` : ''}</span></span>
  }
  const columns: TableColumn<Row>[] = [
    { id: 'location', header: labels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name : <button type="button" className="drilldown-table__link"
        onClick={() => setPath(row.path ?? [...path, row.name])}>{row.name}</button> },
    ...measures.flatMap(({ metric, label }): TableColumn<Row>[] => {
      const change = metric === 'net_change' ? { favorable: 'increase' as const } : undefined
      return [
        { id: `${metric}_average`, header: `Avg. ${label}/month`, numeric: true, change,
          value: row => row.months[metric].reduce((sum, value) => sum + value, 0) / months.length,
          format: value => formatValue(metric, Number(value)) },
        { id: `${metric}_highest`, header: `Highest month ${label}`, numeric: true, change,
          value: row => extreme(row, metric, true), format: (_, row) => extremeLabel(row, metric, true) },
        { id: `${metric}_lowest`, header: `Lowest month ${label}`, numeric: true, change,
          value: row => extreme(row, metric, false), format: (_, row) => extremeLabel(row, metric, false) },
      ]
    }),
  ]
  const filterNotes = measures.flatMap(({ tab }) => {
    const filter = monthlyFilter[tab as keyof typeof monthlyFilter]
    const values = filter ? params.getAll(filter.search) : []
    return values.length ? [`${filter.label} ${values.join(', ')}.`] : []
  })
  return <>
    <DrilldownNavigation locationView={locationView} items={[
      ...path.map((name, index) => ({ id: String(index), label: name, onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} level={{ current: depth + 1, total: 4, label: labels[depth] }} />
    <DrilldownTable title={`${labels[depth]} admissions, discharges and net change`}
      subtitle={['Monthly averages and the highest and lowest month of each. Coming from narrows admissions and '
        + 'Going to narrows discharges; net change is census, which neither divides.', ...filterNotes].join(' ')}
      columns={columns} rows={[...groups.values()]} getRowKey={row => row.key}
      getFooterRow={rows => ({ key: 'total', name: 'Total', isTotal: true,
        months: Object.fromEntries(measures.map(({ metric }) => [metric,
          months.map((_, index) => rows.reduce((sum, row) => sum + row.months[metric][index], 0))])) as Row['months'],
      })}
      initialSort={{ columnId: 'location', direction: 'ascending' }} stickyFirstColumn
      loading={references.loading || result === null}
      error={references.error ?? result?.error}
      onRetry={references.error ? references.onRetry : () => setRetry(value => value + 1)}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No locations match the selected range and payers."
      csvFileName={`monthly-adt-locations-${startDate}-to-${endDate}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={path => { setPath(path); setShowFacilities(false) }}
      filters={<MonthlyAdtFilters />}
      title={`All facilities · ADT by month, ${dayjs(startDate).format('MMM YYYY')} to ${dayjs(endDate).format('MMM YYYY')}`}
      subtitle="Monthly averages and the highest and lowest month of admissions, discharges and net change, per facility."
      rows={[...facilityRows.values()]} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => row.place ?? ['', '', '']}
      loading={references.loading || result === null} error={references.error ?? result?.error}
      onRetry={references.error ? references.onRetry : () => setRetry(value => value + 1)}
      csvFileName={`monthly-adt-facilities-${startDate}-to-${endDate}.csv`} />
  </>
}
