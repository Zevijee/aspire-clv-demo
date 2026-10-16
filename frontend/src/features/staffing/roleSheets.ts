import { useEffect, useRef } from 'react'
import { type TableColumn } from '../../shared/components/Table'
import { registerExcelSheets } from '../../shared/exportExtensions'
import { tableToExcel } from '../../shared/reportExcel'
import { type DrilldownRow } from '../../shared/utils/locationDrilldown'
import { STAFFING_ROLES } from './api'
import { departmentSections, type RoleRow } from './departmentSections'

/** A Staffing report's Excel export: a Total sheet with the report's role table
 * over everything the drilldown shows, then a sheet for each location in it --
 * each state at the top, each facility in a region -- with the role table over
 * that location's facilities. Departments then their roles, and All roles, in the
 * role table's columns. Roles only: each role's employees used to fold under
 * it, some 44,000 hidden rows on the Total sheet, and were not wanted. */
export function useRoleSheets<Item extends { facility_name: string }>({
  locations, scopeName, title, columns,
}: {
  /** The drilldown table's rows, at its current level. */
  locations: DrilldownRow<Item>[]
  /** What the drilldown shows as a whole, for the Total sheet's title. */
  scopeName: string
  /** The role table's title, after the location's name. */
  title: string
  columns: TableColumn<RoleRow<Item>>[]
}) {
  const build = () => {
    const sheet = (name: string, sheetTitle: string, facilities: Item[]) => tableToExcel<RoleRow<Item>>({
      name,
      title: sheetTitle,
      columns,
      rows: STAFFING_ROLES.map(role => ({ key: role.value, name: role.label, path: [], facilities, codes: [role.value] })),
      sections: departmentSections(facilities),
      footer: { key: 'total', name: 'All roles', path: [], isTotal: true, facilities,
        codes: STAFFING_ROLES.map(role => role.value) },
    })
    return [
      sheet('Total', `${scopeName} · ${title}`, locations.flatMap(location => location.facilities)),
      ...locations.map(location => sheet(location.name, `${location.name} · ${title}`, location.facilities)),
    ]
  }
  // Asked at export time, for the locations and figures on screen then.
  const latest = useRef(build)
  useEffect(() => { latest.current = build })
  useEffect(() => registerExcelSheets(() => latest.current()), [])
}
