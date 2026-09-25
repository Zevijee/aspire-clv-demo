import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { DESTINATION_TYPES, SOURCE_TYPES } from '../api/monthlyAdt'

type Props = { values: string[]; onChange: (values: string[]) => void }

/** Where admitted residents came from. One definition for the report header and
 * the modals that cover it. */
export function AdmissionSourceFilter({ values, onChange }: Props) {
  return <FilterDropdown label="Source type" placeholder="All sources"
    options={SOURCE_TYPES.map(value => ({ value, label: value }))} values={values} onChange={onChange} />
}

/** Where discharged residents went. */
export function DischargeDestinationFilter({ values, onChange }: Props) {
  return <FilterDropdown label="Destination type" placeholder="All destinations"
    options={DESTINATION_TYPES.map(value => ({ value, label: value }))} values={values} onChange={onChange} />
}
