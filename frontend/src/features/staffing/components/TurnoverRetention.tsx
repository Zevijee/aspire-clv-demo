import { useEffect, useState, type ReactNode } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useLocationSheets } from '../../../shared/locationSheets'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getTurnover, STAFFING_ROLES, type FacilityTurnover, type RoleTurnover, type TurnoverReport } from '../api'
import { departmentSections, type RoleRow as DepartmentRoleRow } from '../departmentSections'
import { formatMeasure as format } from '../laborCost'
import { perRow } from '../perRow'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { TurnoverPeopleModal, type TurnoverWindow } from './TurnoverPeople'

type Row = DrilldownRow<FacilityTurnover>
type RoleRow = DepartmentRoleRow<FacilityTurnover>
type Counts = Record<keyof RoleTurnover, number>

const COUNTED: (keyof RoleTurnover)[] = ['start_headcount', 'end_headcount', 'hires', 'departures', 'retained',
  'eligible_90', 'retained_90', 'tenure_days']

/** Some roles' counts over some facilities, summed before anything is divided. */
function sum(facilities: FacilityTurnover[], roles: string[]): Counts {
  const counts = Object.fromEntries(COUNTED.map(key => [key, 0])) as Counts
  for (const facility of facilities) {
    for (const code of roles) {
      const role = facility.roles[code]
      if (role) for (const key of COUNTED) counts[key] += role[key]
    }
  }
  return counts
}

const percent = (value: number | string) => typeof value === 'number' ? `${value.toFixed(1)}%` : value

/** The columns, each from the summed counts: headcount, its movement, the rates
 * divided once, and tenure. */
function metricColumns<Item>(counts: (row: Item) => Counts, days: number): TableColumn<Item>[] {
  const share = (part: number, whole: number) => whole > 0 ? part / whole * 100 : '—'
  return [
    { id: 'start', header: 'Start', group: 'Headcount', numeric: true, value: row => counts(row).start_headcount,
      format: value => format(value, 'count') },
    { id: 'end', header: 'End', group: 'Headcount', numeric: true, value: row => counts(row).end_headcount,
      format: value => format(value, 'count') },
    // The end less the start: the hires less the departures. Green when the staff grew.
    { id: 'net', header: 'Net change', group: 'Headcount', numeric: true, change: { favorable: 'increase' },
      value: row => counts(row).end_headcount - counts(row).start_headcount,
      format: value => format(value, 'signedHours') },
    { id: 'hires', header: 'Hires', group: 'Movement', numeric: true, value: row => counts(row).hires,
      format: value => format(value, 'count') },
    { id: 'departures', header: 'Departures', group: 'Movement', numeric: true, value: row => counts(row).departures,
      format: value => format(value, 'count') },
    { id: 'turnover', header: 'Turnover (annualized)', group: 'Rates', numeric: true,
      value: row => {
        const { start_headcount: start, end_headcount: end, departures } = counts(row)
        const average = (start + end) / 2
        return average > 0 && days > 0 ? departures / average * (365 / days) * 100 : '—'
      },
      format: percent },
    { id: 'retention', header: 'Retention', group: 'Rates', numeric: true,
      value: row => share(counts(row).retained, counts(row).start_headcount), format: percent },
    { id: 'retention_90', header: '90-day retention', group: 'Rates', numeric: true,
      value: row => share(counts(row).retained_90, counts(row).eligible_90), format: percent },
    { id: 'tenure', header: 'Avg. tenure (years)', group: 'Tenure', numeric: true,
      value: row => counts(row).end_headcount > 0 ? counts(row).tenure_days / counts(row).end_headcount / 365.25 : '—',
      format: value => typeof value === 'number' ? value.toFixed(1) : value },
  ]
}

/** Turnover and Retention: each location's own employees over the header's
 * date range -- headcount before it and at its end, the hires and departures
 * between, turnover scaled to a year, how many of those there at the start were
 * still there at the end, how many new hires reached 90 days, and how long the
 * people there at the end had been -- drilled from state to facility, and below,
 * one row per department followed by its roles, each name, and its Hires and
 * Departures, opening the people behind it and why they left. Agency staff are not counted:
 * they are not the facility's employees. Everything is summed first and divided
 * once. */
export function TurnoverRetention({ initialPath }: { initialPath?: string[] } = {}) {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // One drill= per level, in order; the Excel export's copy for a location starts there instead.
  const path = initialPath ?? params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(level => updated.append('drill', level))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<TurnoverReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getTurnover(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error
  const days = data?.days ?? 0

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The Excel export's sheet for each location in the table, this tab drilled into it.
  useLocationSheets(() => path.length === 4 ? [] : rows.map(row => ({ name: row.name,
    render: () => <TurnoverRetention initialPath={row.path} /> })))
  // The drilldown's roles, from its own filter; the role table lists every role.
  const { roles, roleName, filter: roleFilter } = useDrilldownRoles()
  // Each row's counts once, however many columns and sorts ask.
  const locationCounts = perRow((row: Row) => sum(row.facilities, roles))
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityTurnover>(depth, path, setPath),
    ...metricColumns<Row>(locationCounts, days),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const subtitle = `The facilities' own employees, ${roleName}, ${range}; agency staff are not counted. Headcount is `
    + 'who was employed the day before the range and on its last day, the hires and departures between them. '
    + 'Turnover is the departures over the average of the two headcounts, scaled to a year; retention the share of '
    + 'those there at the start still there at the end; 90-day retention the share of new hires whose 90th day fell '
    + 'in the range still employed on it; and average tenure how long those there at the end had been.'
  const file = `${shownStart}-to-${shownEnd}`

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role with its counts over the facilities shown.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  const roleCounts = perRow((row: RoleRow) => sum(row.facilities, row.codes))
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  // The locations shown, as the people list's filters: the drilldown's path,
  // level by level, or with a custom grouping, its facilities.
  const locationFilters: Record<string, string[]> = grouping
    ? (path.length ? { facility: scoped.map(facility => facility.facility_name) } : {})
    : Object.fromEntries(path.map((name, index) => [['state', 'portfolio', 'region', 'facility'][index], [name]]))
  // A role's, department's or All roles' name opens its hires and departures;
  // a Hires or Departures figure, those only.
  const [peopleScope, setPeopleScope] = useState<TurnoverWindow | null>(null)
  const peopleLink = (content: ReactNode, row: RoleRow, event?: 'Hired' | 'Left') => <button type="button"
    className="drilldown-table__link"
    title={`Show who ${event === 'Hired' ? 'was hired' : event === 'Left' ? 'left' : 'was hired or left'}: ${row.name}`}
    onClick={() => setPeopleScope({ name: `${row.name} · ${scopeName}${event ? ` · ${event === 'Hired' ? 'Hires' : 'Departures'}` : ''}`,
      roles: row.codes, filters: { ...locationFilters, ...(event ? { event: [event] } : {}) } })}>{content}</button>
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true, format: (_, row) => peopleLink(row.name, row) },
    ...metricColumns<RoleRow>(roleCounts, days).map(column => column.id === 'hires' || column.id === 'departures'
      ? { ...column, format: (value: number | string, row: RoleRow) => typeof value === 'number' && value > 0
        ? peopleLink(format(value, 'count'), row, column.id === 'hires' ? 'Hired' : 'Left') : format(value, 'count') }
      : column),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} turnover and retention`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`turnover-retention-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · Turnover and retention, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`turnover-retention-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title="Turnover and retention by role" columns={roleColumns}
      rows={roleRows} sections={departmentSections(scoped)}
      // Every role over the facilities shown, summed and divided once.
      getFooterRow={visible => ({ key: 'total', name: 'All roles', path: [], isTotal: true, facilities: scoped,
        codes: visible.flatMap(row => row.codes) })}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. Each department's employees over the facilities shown, `
        + 'followed by its roles. A name, or its Hires or Departures, lists the people and why they left.'}
      emptyMessage="No roles match this view."
      csvFileName={`turnover-retention-roles-${file}.csv`} />
    <TurnoverPeopleModal scope={peopleScope} startDate={shownStart} endDate={shownEnd} onClose={() => setPeopleScope(null)} />
  </>
}
