import { useEffect, useState, type ReactNode } from 'react'
import { registerReportExport } from '../../shared/exportExtensions'
import { type CustomGrouping } from '../../shared/customGrouping'
import { type DrilldownRow } from '../../shared/utils/locationDrilldown'
import { type FacilityOverview } from './api'
import { StaffingEmployeesModal, type EmployeesWindow } from './components/StaffingEmployeesModal'
import { type RoleRow } from './departmentSections'
import { employeesExportExtra } from './employeesExport'

type Row = DrilldownRow<FacilityOverview>

/** The Staffing Overview tabs' links from a figure to the people behind it,
 * shared by the Simple and Full overviews, each opening a window over the page
 * rather than another view: an overtime figure, the employees with overtime for
 * its row; a role's or department's name, its employees. Both over the
 * locations shown. */
export function useStaffingDrillLinks({ path, grouping, scoped, roles, roleName, startDate, endDate, enabled = true }: {
  /** The drilldown's path and custom grouping, and the facilities it shows. */
  path: string[]
  grouping: CustomGrouping | null
  scoped: FacilityOverview[]
  /** The location table's roles, from its role filter. */
  roles: string[]
  roleName: string
  startDate: string
  endDate: string
  /** Off for a report that shows no such links: nothing is added to its export. */
  enabled?: boolean
}) {
  const [open, setOpen] = useState<EmployeesWindow | null>(null)
  // The HTML export carries the employees, so these links open the same lists
  // in the file (employeesExport).
  useEffect(() => enabled ? registerReportExport(() => employeesExportExtra(startDate, endDate)) : undefined,
    [enabled, startDate, endDate])
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  // A row's locations as the list's filters: its path, level by level, or with a
  // custom grouping, whose groups are any facilities, their names.
  const locationFilters = (rowPath: string[], facilities: FacilityOverview[]): Record<string, string[]> => {
    if (grouping) return rowPath.length ? { facility: facilities.map(facility => facility.facility_name) } : {}
    const filters: Record<string, string[]> = {}
    ;['state', 'portfolio', 'region', 'facility'].forEach((key, index) => {
      if (rowPath[index]) filters[key] = [rowPath[index]]
    })
    return filters
  }
  const link = (content: ReactNode, scope: EmployeesWindow) => <button type="button"
    className="drilldown-table__link"
    title={`Show the ${scope.overtime ? 'employees with overtime' : 'employees'} behind ${scope.name}`}
    // What it opens, for the exported file's script, which has no React.
    data-employees={JSON.stringify(scope)}
    onClick={() => setOpen(scope)}>{content}</button>

  return {
    /** A location row's overtime figure: the total row stands for the drilldown's scope. */
    locationOvertime: (content: ReactNode, row: Row) => link(content, {
      name: `${row.isTotal ? scopeName : row.name} · ${roleName}`, roles, overtime: true,
      filters: locationFilters(row.isTotal ? path : row.path, row.facilities),
    }),
    /** A role row's overtime figure: the role, or every role of its department. */
    roleOvertime: (content: ReactNode, row: RoleRow<FacilityOverview>) => link(content, {
      name: `${row.name} · ${scopeName}`, roles: row.codes, overtime: true, filters: locationFilters(path, scoped),
    }),
    /** A role's or department's name: its employees. */
    roleName: (row: RoleRow<FacilityOverview>) => link(row.name, {
      name: `${row.name} · ${scopeName}`, roles: row.codes, overtime: false, filters: locationFilters(path, scoped),
    }),
    /** The window, to render once on the page. */
    modal: <StaffingEmployeesModal scope={open} startDate={startDate} endDate={endDate} onClose={() => setOpen(null)} />,
  }
}
