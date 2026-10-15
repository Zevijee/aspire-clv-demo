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
import { getStaffingOverview, STAFFING_ROLES, type FacilityOverview, type StaffingOverview as Report } from '../api'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { formatMetric, metric } from './StaffingOverview'
import { useStaffingDrillLinks } from '../drillLinks'
import { departmentSections, type RoleRow as DepartmentRoleRow } from '../departmentSections'
import { type MeasureKind } from '../laborCost'

type Row = DrilldownRow<FacilityOverview>
type RoleRow = DepartmentRoleRow<FacilityOverview>

/** One column: a Staffing Overview figure by its id, under this report's own
 * header, for a signed figure which way is good, and the section it sits in. */
export type SectionMetric = [id: string, header: string, kind: MeasureKind, change?: 'increase' | 'neutral',
  group?: string]

type Props = {
  /** The report's name, as the tables' titles and file names use it: "Hourly rate". */
  name: string
  metrics: SectionMetric[]
  /** What the drilldown's columns mean, for the chosen roles' name and the range. */
  describe: (roleNames: string, range: string) => string
  /** What the role table's rows add up. */
  roleNote: string
  /** These columns' figures open the employees with overtime behind them. A
   * role's or department's name always opens its employees. */
  overtimeLinks?: string[]
}

/** A Staffing report that shows one part of the Staffing Overview on its own:
 * its figures over the header's date range, drilled from state to facility,
 * and below, one row per department followed by its roles. The figures are the
 * Overview's own (its metric), read from the same response, so the two always
 * agree. The drilldown is kept in the URL. */
export function StaffingSectionReport({ name, metrics, describe, roleNote, overtimeLinks }: Props) {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // One drill= per level, in order.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(level => updated.append('drill', level))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getStaffingOverview(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error
  const days = data?.days ?? Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86_400_000) + 1
  const premiums = { overtime: data?.overtime_premium ?? 0.5, holiday: data?.holiday_premium ?? 0.5 }

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The drilldown's roles, from its own filter; the role table lists every role.
  const { roles, roleName, filter: roleFilter } = useDrilldownRoles()
  const shownStartDate = data?.start_date ?? startDate
  const shownEndDate = data?.end_date ?? endDate
  const links = useStaffingDrillLinks({ path, grouping, scoped: rows.flatMap(row => row.facilities), roles, roleName,
    startDate: shownStartDate, endDate: shownEndDate })
  const linked = new Set(overtimeLinks ?? [])
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityOverview>(depth, path, setPath),
    ...metrics.map(([id, header, kind, change, group]): TableColumn<Row> => ({
      id, header, group, numeric: true, value: row => metric(row, id, days, premiums, roles) ?? '—',
      format: (value: number | string, row: Row) => {
        const shown = formatMetric(id, kind, value, row, days, premiums, roles)
        return linked.has(id) && typeof value === 'number' ? links.locationOvertime(shown, row) : shown
      },
      ...(change ? { change: { favorable: change } } : {}),
    })),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const subtitle = describe(roleName, range)
  const file = `${shownStart}-to-${shownEnd}`
  // "Premiums and extras" titles a table "State premiums and extras" and names its file premiums-and-extras-....
  const lower = name.toLowerCase()
  const slug = lower.replace(/[^a-z0-9]+/g, '-')

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role with its totals over the facilities shown.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true, format: (_, row) => links.roleName(row) },
    ...metrics.map(([id, header, kind, change, group]): TableColumn<RoleRow> => ({
      id, header, group, numeric: true, value: row => metric(row, id, days, premiums, row.codes) ?? '—',
      format: (value: number | string, row: RoleRow) => {
        const shown = formatMetric(id, kind, value, row, days, premiums, row.codes)
        return linked.has(id) && typeof value === 'number' ? links.roleOvertime(shown, row) : shown
      },
      ...(change ? { change: { favorable: change } } : {}),
    })),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} ${lower}`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`${slug}-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · ${name}, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`${slug}-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title={`${name} by role`} columns={roleColumns} rows={roleRows}
      sections={departmentSections(scoped)}
      // Every role over the facilities shown, summed and divided once.
      getFooterRow={visible => ({ key: 'total', name: 'All roles', path: [], isTotal: true, facilities: scoped,
        codes: visible.flatMap(row => row.codes) })}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. ${roleNote}`}
      emptyMessage="No roles match this view."
      csvFileName={`${slug}-roles-${file}.csv`} />
    {links.modal}
  </>
}
