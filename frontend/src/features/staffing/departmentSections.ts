import { type TableSections } from '../../shared/components/Table'
import { type DrilldownRow } from '../../shared/utils/locationDrilldown'
import { STAFFING_ROLES } from './api'

/** A row of a role table: one role over the drilldown's facilities. `codes` is
 * the role, or every role it adds up for a department. */
export type RoleRow<Item> = DrilldownRow<Item> & { codes: string[] }

/** A staffing role table's sections: each department -- Admin & General,
 * Direct Care, Non-Nursing, Nursing Admin -- followed by its roles. A
 * department's row is its roles' figures over the same facilities, summed and
 * divided once, never the role rows added up. */
export function departmentSections<Item>(facilities: Item[]): TableSections<RoleRow<Item>> {
  return {
    getPath: row => {
      const role = STAFFING_ROLES.find(entry => entry.value === row.codes[0])
      return role ? [role.context] : []
    },
    getRow: (path, rows) => ({ key: `section:${path.join('/')}`, name: path[path.length - 1], path: [], facilities,
      codes: rows.map(row => row.codes[0]) }),
  }
}
