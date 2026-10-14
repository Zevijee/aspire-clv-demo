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
import { getOvertime, STAFFING_ROLES, type FacilityOvertime, type OvertimeReport } from '../api'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { departmentSections } from '../departmentSections'

type Row = DrilldownRow<FacilityOvertime>
// A row of the role table: one role over the drilldown's facilities. `codes` is
// the role, or every role shown for the Total row.
type RoleRow = Row & { codes: string[] }
type Kind = 'hours' | 'share' | 'count' | 'rate' | 'money'

const metrics: [id: string, header: string, kind: Kind][] = [
  ['hours', 'Hours worked', 'hours'],
  ['overtime_hours', 'Overtime hours', 'hours'],
  ['share', 'Overtime share', 'share'],
  ['overtime_shifts', 'Shifts with overtime', 'count'],
  ['rate', 'Avg. hourly rate', 'rate'],
  ['premium', 'Overtime premium', 'money'],
]

// The chosen roles' sums at this scope.
function sums(row: Row, roles: string[]) {
  const total = { hours: 0, wages: 0, overtimeHours: 0, overtimeWages: 0, overtimeShifts: 0 }
  for (const facility of row.facilities) {
    for (const code of roles) {
      const role = facility.roles[code]
      if (!role) continue
      total.hours += role.hours
      total.wages += role.wages
      total.overtimeHours += role.overtime_hours
      total.overtimeWages += role.overtime_wages
      total.overtimeShifts += role.overtime_shifts
    }
  }
  return total
}

// Summed at this scope, then divided once: never an average of facility shares.
function metric(row: Row, id: string, roles: string[], premium: number): number | null {
  const total = sums(row, roles)
  if (id === 'hours') return total.hours
  if (id === 'overtime_hours') return total.overtimeHours
  if (id === 'share') return total.hours > 0 ? total.overtimeHours / total.hours : null
  if (id === 'overtime_shifts') return total.overtimeShifts
  if (id === 'rate') return total.hours > 0 ? total.wages / total.hours : null
  return total.overtimeWages * premium
}

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (kind === 'money') return `$${Math.round(value).toLocaleString()}`
  if (kind === 'share') return `${(value * 100).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}


/** Overtime: the hours worked in the header's date range, drilled from state to
 * facility, with the hours over 40 a week per employee, their share, who worked
 * and who went over, the average rate and what time-and-a-half would add.
 * Below it, one row per role for the drilldown's scope. The drilldown is kept in the URL. */
export function OvertimeDrilldown() {
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
  const [data, setData] = useState<OvertimeReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // Every role, as HPPD's Overview: the table adds them all up and the role
  // table lists each. The Trending tab has the role picker.
  // The drilldown's roles, from its own filter; the role table lists every role.
  const { roles, roleName, filter: roleFilter } = useDrilldownRoles()
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getOvertime(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error
  const weeklyHours = data?.weekly_hours ?? 40
  const premium = data?.premium ?? 0.5

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityOvertime>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id, roles, premium) ?? '—',
      format: (value: number | string) => format(value, kind),
    })),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const subtitle = `Hours worked, ${roleName}, ${range}, and the hours over ${weeklyHours} a week (Monday to Sunday) per `
    + 'employee. Overtime share is overtime hours over hours worked; Shifts with overtime counts the employee-days with '
    + 'any. The average rate is wages over hours. The facts pay straight time, so Overtime premium is '
    + `what time-and-a-half would add: ${premium * 100}% of the overtime hours' pay. An employee's overtime for a week is `
    + `spread over the days they worked it, so any range shows its days' share.`
  const file = `${shownStart}-to-${shownEnd}`

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role, with that role's totals over the facilities shown,
  // each summed at this scope and divided once.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true },
    ...metrics.map(([id, header, kind]): TableColumn<RoleRow> => ({
      id, header, numeric: true, value: row => metric(row, id, row.codes, premium) ?? '—',
      format: (value: number | string) => format(value, kind),
    })),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} overtime`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`overtime-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · Overtime, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`overtime-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title="Overtime by role" columns={roleColumns} rows={roleRows}
      sections={departmentSections(scoped)}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. Each role's hours and overtime over the facilities shown, `
        + 'with its share and average rate divided once. Each department is followed by its roles.'}
      emptyMessage="No roles match this view."
      csvFileName={`overtime-roles-${file}.csv`} />
  </>
}
