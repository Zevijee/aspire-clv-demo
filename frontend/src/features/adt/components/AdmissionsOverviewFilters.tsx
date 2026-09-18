import { TabFilterBar } from '../../../shared/components/filters/TabFilterBar'
import { payerCode, payerLabel } from '../api/admissionsOverview'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import {
  overviewFilterValues, overviewFilterSettings,
  overviewSelection, type OverviewSelection,
} from '../utils/admissionsOverviewFilters'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'

const sources = ['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility', 'Assisted Living', 'Community']

export function AdmissionsOverviewFilters({ selection, onChange }: {
  selection: OverviewSelection
  onChange: (selection: OverviewSelection) => void
}) {
  const reference = useAdmissionsReferences()
  const locations = (reference.data?.locations ?? []).map(row => ({
    state: row.state, portfolio: row.portfolio_name, region: row.region_name, facility: row.facility_name,
  }))
  const values = overviewFilterValues(selection)
  return <TabFilterBar ariaLabel="Overview filters"
    settings={overviewFilterSettings(selection)}
    onApplyFilters={(draft) => onChange(overviewSelection(draft))}
    filters={[
      {
        id: 'location', label: 'Location', values: values.location,
        isApplied: selection.scope !== null,
        options: [],
        renderPicker: (props) => <AdmissionsLocationPicker {...props} locations={locations} />,
        isLoading: reference.loading, error: reference.error, onRetry: reference.onRetry,
      },
      { id: 'payer', label: 'Payer types', values: values.payer.map(payerCode),
        isLoading: reference.loading, error: reference.error, onRetry: reference.onRetry,
        options: (reference.data?.payerTypes ?? []).map(value => ({ value, label: payerLabel(value) })) },
      { id: 'source', label: 'Source types', values: values.source,
        options: sources.map((value) => ({ value, label: value })) },
    ]} />
}
