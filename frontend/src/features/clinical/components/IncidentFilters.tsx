import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { AdmissionsPayerFilter } from '../../adt/components/AdmissionsPayerFilter'
import { INCIDENT_TYPES, SEVERITY_LEVELS } from '../api'

// The URL parameters the donuts and these dropdowns share.
export const INCIDENT_PAYER_PARAM = 'incident_payer'
export const INCIDENT_TYPE_PARAM = 'incident_type'
export const INCIDENT_SEVERITY_PARAM = 'incident_severity'

/** Incidents' header filters, beside the date range. Type and severity are the
 * same filters its donuts set, so either one changes the other. */
export function IncidentFilters() {
  const payers = useSearchParamList(INCIDENT_PAYER_PARAM)
  const types = useSearchParamList(INCIDENT_TYPE_PARAM)
  const severities = useSearchParamList(INCIDENT_SEVERITY_PARAM)
  return <>
    <AdmissionsPayerFilter values={payers.values} onChange={payers.set} />
    <FilterDropdown label="Incident types" placeholder="All incident types"
      options={INCIDENT_TYPES.map(kind => ({ value: kind, label: kind }))}
      values={types.values} onChange={types.set} />
    <FilterDropdown label="Severity" placeholder="All levels"
      options={Object.entries(SEVERITY_LEVELS).map(([value, label]) => ({ value, label }))}
      values={severities.values} onChange={severities.set} />
  </>
}
