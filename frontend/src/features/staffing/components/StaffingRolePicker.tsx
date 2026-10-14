import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { STAFFING_ROLES } from '../api'

/** A Trending tab's role filter: any set of roles, added up together, or with
 * none picked every role. Kept in the URL under the given parameter, so a
 * report's tabs share it. Returns the chosen role codes (empty for every
 * role), how to name them in a subtitle, and the Roles dropdown -- roles under
 * their departments -- for the trend table's `filters` slot and its Show all
 * facilities view's, so both change the same selection. Twenty-two roles made
 * a button row three rows tall; the dropdown is the drilldown tables' own. */
export function useStaffingRoles(param: string) {
  const picks = useSearchParamList(param)
  const picked = picks.values.filter(code => STAFFING_ROLES.some(role => role.value === code))
  const roleName = picked.length
    ? STAFFING_ROLES.filter(role => picked.includes(role.value)).map(role => role.label).join(', ') : 'every role'
  const picker = <FilterDropdown label="Roles" placeholder="All roles" variant="detailed" groupByContext
    options={STAFFING_ROLES.map(role => ({ value: role.value, label: role.label, context: role.context }))}
    values={picked} onChange={picks.set} />
  return { roles: picked, roleName, picker }
}
