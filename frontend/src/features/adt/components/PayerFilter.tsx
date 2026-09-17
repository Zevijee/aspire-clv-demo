import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { formatPayerType } from '../api/admissions'

const payers = ['Medicare', 'Medicare Advantage', 'Medicare HMO', 'Managed Medicaid', 'Medicaid', 'Hospice', 'Private Pay']

export function PayerFilter({ values, onChange, displayValues = false }: {
  values: string[]
  onChange: (values: string[]) => void
  displayValues?: boolean
}) {
  return <FilterDropdown label="Payers" placeholder="All payers"
    options={payers.map(payer => ({ value: displayValues ? formatPayerType(payer) : payer, label: formatPayerType(payer) }))}
    values={values} onChange={onChange} />
}
