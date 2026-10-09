import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { ROLE_PARAM, STAFFING_ROLES } from '../api'

/** PPD's header filter, beside the date range: which roles the drilldown adds
 * up, kept in the URL. Empty means every role. */
export function StaffingRoleFilter() {
  const roles = useSearchParamList(ROLE_PARAM)
  return <FilterDropdown label="Roles" placeholder="All roles" options={STAFFING_ROLES}
    values={roles.values} onChange={roles.set} />
}
