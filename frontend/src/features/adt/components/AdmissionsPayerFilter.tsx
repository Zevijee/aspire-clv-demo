import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { payerCode, payerLabel } from '../api/admissionsOverview'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'

export function AdmissionsPayerFilter({ values, onChange }: {
  values: string[]; onChange: (values: string[]) => void
}) {
  const reference = useAdmissionsReferences()
  return <FilterDropdown label="Payers" placeholder="All payers"
    options={(reference.data?.payerTypes ?? []).map(value => ({ value, label: payerLabel(value) }))}
    values={values.map(payerCode)} onChange={onChange}
    loading={reference.loading} error={reference.error} onRetry={reference.onRetry} />
}
