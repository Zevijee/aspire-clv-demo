import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { STAFFING_ROLES } from '../api'

// The drilldown table's role filter, kept in the URL so the table and its Show
// all facilities view share it, and a refresh keeps it.
export const DRILLDOWN_ROLE_PARAM = 'drill_role'

/** A staffing report's role filter for its location drilldown table only --
 * the role table and the report's other tabs are not narrowed by it. Returns
 * the roles the drilldown adds up (every role when none is picked), how to
 * name them in a subtitle, and the dropdown, for the table's `filters` slot
 * and the Show all facilities view's, so both change the same selection. */
export function useDrilldownRoles() {
  const picks = useSearchParamList(DRILLDOWN_ROLE_PARAM)
  const picked = picks.values.filter(code => STAFFING_ROLES.some(role => role.value === code))
  const roles = picked.length ? picked : STAFFING_ROLES.map(role => role.value)
  const roleName = picked.length
    ? STAFFING_ROLES.filter(role => picked.includes(role.value)).map(role => role.label).join(', ')
    : 'every role'
  // Roles under their departments, in report order.
  const filter = <FilterDropdown label="Roles" placeholder="All roles" variant="detailed" groupByContext
    options={STAFFING_ROLES.map(role => ({ value: role.value, label: role.label, context: role.context }))}
    values={picked} onChange={picks.set} />
  return { roles, roleName, filter }
}
