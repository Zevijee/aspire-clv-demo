import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getPpd, STAFFING_ROLES, type FacilityStaffing, type PpdReport } from '../api'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { departmentSections } from '../departmentSections'

type Row = DrilldownRow<FacilityStaffing>
// A row of the role table: a role over some facilities, or one breakdown item
// under it. `codes` is the role, or every role shown for the Total row.
type RoleRow = Row & { codes: string[] }
type Kind = 'count' | 'average' | 'hours' | 'ppd' | 'variance' | 'rate' | 'money'

const metrics: [id: string, header: string, kind: Kind][] = [
  ['census_days', 'Census days', 'count'],
  ['adc', 'Avg. daily census', 'average'],
  ['hours', 'Hours worked', 'hours'],
  ['ppd', 'HPPD', 'ppd'],
  ['target', 'Target HPPD', 'ppd'],
  ['variance', 'HPPD variance', 'variance'],
  ['excess_hours', 'Extra hours worked', 'hours'],
  ['rate', 'Avg. hourly rate', 'rate'],
  ['excess_wages', 'Excess spend', 'money'],
]
// The role table's columns: the drilldown's, in its order, without the census
// columns, which are the same for every role.
const ROLE_METRICS = ['hours', 'ppd', 'target', 'variance', 'excess_hours', 'rate', 'excess_wages']

// The chosen roles' sums at this scope; census days once per facility, never per
// role, so any set of roles divides by the same census days.
function sums(row: Row, roles: string[]) {
  const total = { censusDays: 0, hours: 0, targetHours: 0, excessHours: 0, wages: 0, excessWages: 0 }
  for (const facility of row.facilities) {
    total.censusDays += facility.census_days
    for (const code of roles) {
      const role = facility.roles[code]
      if (!role) continue
      total.hours += role.hours
      total.targetHours += role.target_hours
      total.excessHours += role.excess_hours
      total.wages += role.wages
      total.excessWages += role.excess_wages
    }
  }
  return total
}

// Summed at this scope, then divided once: never an average of facility HPPDs.
function metric(row: Row, id: string, days: number, roles: string[]): number | null {
  const total = sums(row, roles)
  const perCensusDay = (value: number) => total.censusDays > 0 ? value / total.censusDays : null
  if (id === 'census_days') return total.censusDays
  if (id === 'adc') return days > 0 ? total.censusDays / days : null
  if (id === 'hours') return total.hours
  if (id === 'ppd') return perCensusDay(total.hours)
  if (id === 'target') return perCensusDay(total.targetHours)
  if (id === 'variance') return perCensusDay(total.hours - total.targetHours)
  if (id === 'excess_hours') return total.excessHours
  if (id === 'rate') return total.hours > 0 ? total.wages / total.hours : null
  return total.excessWages
}

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  const fixed = (digits: number) => value.toLocaleString(undefined, { minimumFractionDigits: digits,
    maximumFractionDigits: digits })
  if (kind === 'average') return fixed(1)
  if (kind === 'ppd') return fixed(2)
  if (kind === 'rate') return `$${fixed(2)}`
  if (kind === 'money') return `$${Math.round(value).toLocaleString()}`
  if (kind === 'variance') {
    // Rounded first, so a variance too small to show reads 0.00, never −0.00.
    const shown = Math.round(value * 100) / 100
    return shown === 0 ? '0.00' : `${shown > 0 ? '+' : '−'}${Math.abs(shown).toFixed(2)}`
  }
  return fixed(0)
}

/** HPPD: hours worked per patient day over every role in the header's date range,
 * drilled from state to facility, against target, with the extra hours worked
 * over each day's target and what they cost. Below it, one row per role for
 * the drilldown's scope, each opening to the same breakdown for that role.
 * The drilldown is kept in the URL. */
export function PpdDrilldown() {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const days = Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86_400_000) + 1
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
  const [data, setData] = useState<PpdReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // Every role: the table adds them all up, and the role table lists each.
  // The drilldown's roles, from its own filter; the role table lists every role.
  const { roles, roleName: roleNames, filter: roleFilter } = useDrilldownRoles()
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getPpd(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityStaffing>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id, days, roles) ?? '—',
      format: (value: number | string) => format(value, kind),
      // Over target costs money and under it risks care: neither direction is good.
      ...(id === 'variance' ? { change: { favorable: 'neutral' as const } } : {}),
    })),
  ]
  const range = `${startDate} to ${endDate}`
  const subtitle = `Hours worked per patient day, ${roleNames}, ${range}. Census days are each day's closing census `
    + 'summed; HPPD is hours over census days and target HPPD is target hours over the same days. Extra hours are '
    + 'the hours over each day\'s target at each facility and role. Excess spend is those hours at each day\'s '
    + 'hourly rate.'
  const file = `${startDate}-to-${endDate}`

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role in the header filter, with that role's totals over
  // the facilities shown, each summed at this scope and divided once.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true },
    ...ROLE_METRICS.map((id): TableColumn<RoleRow> => {
      const [, header, kind] = metrics.find(([metricId]) => metricId === id)!
      return {
        id, header, numeric: true, value: row => metric(row, id, days, row.codes) ?? '—',
        format: (value: number | string) => format(value, kind),
        ...(id === 'variance' ? { change: { favorable: 'neutral' as const } } : {}),
      }
    }),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} HPPD`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`hppd-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · HPPD, ${roleNames}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`hppd-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title="HPPD by role" columns={roleColumns} rows={roleRows}
      sections={departmentSections(scoped)}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. Each role's hours over the facilities shown and their `
        + 'census days. Each department is followed by its roles.'}
      emptyMessage="No roles match this view."
      csvFileName={`hppd-roles-${file}.csv`} />
  </>
}
