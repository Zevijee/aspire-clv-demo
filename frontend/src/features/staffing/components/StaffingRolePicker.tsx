import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { STAFFING_ROLES } from '../api'

/** A report's role picker, as PPD's Trending tab has: any set of roles,
 * added up together, or with none picked every role. All roles clears the
 * picks. Kept in the URL under the given parameter, so a report's tabs share
 * it. Returns the chosen role codes (empty for every role), how to name them
 * in a subtitle, and the control to place in the drilldown bar or above a
 * table. */
export function useStaffingRoles(param: string) {
  const picks = useSearchParamList(param)
  const picked = picks.values.filter(code => STAFFING_ROLES.some(role => role.value === code))
  const roleName = picked.length
    ? STAFFING_ROLES.filter(role => picked.includes(role.value)).map(role => role.label).join(', ') : 'every role'
  const picker = <SegmentedControl fullWidth separate tone="accent" label="Roles"
    options={[{ id: 'all', label: 'All roles' }, ...STAFFING_ROLES.map(role => ({ id: role.value, label: role.label }))]}
    values={picked.length ? picked : ['all']}
    onChange={id => id === 'all' ? picks.clear() : picks.toggle(id)} />
  return { roles: picked, roleName, picker }
}
