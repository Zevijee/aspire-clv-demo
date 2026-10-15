import { useEffect, useRef } from 'react'
import { type TableColumn } from '../../shared/components/Table'
import { registerExcelSheets } from '../../shared/exportExtensions'
import { tableToExcel, type ExcelRow } from '../../shared/reportExcel'
import { type DrilldownRow } from '../../shared/utils/locationDrilldown'
import { getEmployeesPacked, STAFFING_ROLES } from './api'
import { departmentSections, type RoleRow } from './departmentSections'

type Person = { name: string; facility: string; role: string; agency: boolean; hours: number; overtime: number;
  wages: number }

// What an employee shows in a role table's column, by the column's id: the hours
// they worked and how; nothing for what is not counted per person -- budget,
// HPPD, census, orientation. An agency employee's hours are all agency, as the
// report counts them; an in-house employee's are regular and overtime.
const EMPLOYEE_MEASURES: Record<string, (person: Person) => number | null> = {
  simple_regular_hours: person => person.agency ? null : person.hours - person.overtime,
  simple_overtime_hours: person => person.agency ? null : person.overtime,
  overtime_hours: person => person.agency ? null : person.overtime,
  hours_overtime: person => person.agency ? null : person.overtime,
  simple_agency_hours: person => person.agency ? person.hours : null,
  agency_hours: person => person.agency ? person.hours : null,
  hours_agency: person => person.agency ? person.hours : null,
  inhouse_hours: person => person.agency ? null : person.hours,
  hours_worked: person => person.hours,
  hours: person => person.hours,
}

const tenths = (value: number) => value.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** A Staffing report's Excel export: a Total sheet with the report's role table
 * over everything the drilldown shows, then a sheet for each location in it --
 * each state at the top, each facility in a region -- with the role table over
 * that location's facilities. Departments then their roles, and All roles, in the
 * role table's columns; each role opens, with Excel's +, to its employees there
 * and their hours in the same columns. */
export function useRoleSheets<Item extends { facility_name: string }>({
  locations, scopeName, title, columns, startDate, endDate,
}: {
  /** The drilldown table's rows, at its current level. */
  locations: DrilldownRow<Item>[]
  /** What the drilldown shows as a whole, for the Total sheet's title. */
  scopeName: string
  /** The role table's title, after the location's name. */
  title: string
  columns: TableColumn<RoleRow<Item>>[]
  startDate: string
  endDate: string
}) {
  const build = async () => {
    const data = await getEmployeesPacked(startDate, endDate)
    const people: Person[] = data.rows.map(row => {
      const [name, facility, role, type, , , , , hours, wages, overtime] = row as [string, number, string, string,
        number, string, string, number, number, number, number]
      return { name, facility: data.facilities[facility][0], role, agency: type === 'Agency', hours, overtime, wages }
    }).sort((a, b) => a.name.localeCompare(b.name))
    const sheet = (name: string, sheetTitle: string, facilities: Item[]) => {
      const names = new Set(facilities.map(facility => facility.facility_name))
      return tableToExcel<RoleRow<Item>>({
        name,
        title: sheetTitle,
        columns,
        rows: STAFFING_ROLES.map(role => ({ key: role.value, name: role.label, path: [], facilities, codes: [role.value] })),
        sections: departmentSections(facilities),
        footer: { key: 'total', name: 'All roles', path: [], isTotal: true, facilities,
          codes: STAFFING_ROLES.map(role => role.value) },
        details: (row, shown) => people
          .filter(person => person.role === row.codes[0] && names.has(person.facility))
          .map((person): ExcelRow => ({ cells: shown.map((column, index) => {
            if (index === 0) return person.name
            const value = EMPLOYEE_MEASURES[column.id]?.(person)
            return value === null || value === undefined ? '' : tenths(value)
          }) })),
      })
    }
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
