import { useEffect, useState } from 'react'
import { TabFilterBar } from '../../../shared/components/filters/TabFilterBar'
import { formatPayerType, getAdmissionsFilterOptions, type AdmissionsFilterOptions } from '../api/admissions'
import {
  overviewFilterValues, overviewFilterSettings,
  overviewSelection, type OverviewSelection,
} from '../utils/admissionsOverviewFilters'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'

const payers = ['Medicare', 'Medicare Advantage', 'Medicare HMO', 'Managed Medicaid', 'Medicaid', 'Hospice', 'Private Pay']
const sources = ['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility', 'Assisted Living', 'Community']

export function AdmissionsOverviewFilters({ selection, onChange }: {
  selection: OverviewSelection
  onChange: (selection: OverviewSelection) => void
}) {
  const [attempt, setAttempt] = useState(0)
  const [response, setResponse] = useState<{ attempt: number; data?: AdmissionsFilterOptions; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getAdmissionsFilterOptions().then(
      (data) => { if (active) setResponse({ attempt, data }) },
      () => { if (active) setResponse({ attempt, error: 'Location options could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [attempt])
  const result = response?.attempt === attempt ? response : null
  const values = overviewFilterValues(selection)
  return <TabFilterBar ariaLabel="Overview filters"
    settings={overviewFilterSettings(selection)}
    onApplyFilters={(draft) => onChange(overviewSelection(draft))}
    filters={[
      {
        id: 'location', label: 'Location', values: values.location,
        isApplied: selection.scope !== null,
        options: [],
        renderPicker: (props) => <AdmissionsLocationPicker {...props} locations={result?.data?.locations ?? []} />,
        isLoading: result === null, error: result?.error, onRetry: () => setAttempt((value) => value + 1),
      },
      { id: 'payer', label: 'Payer types', values: values.payer,
        options: payers.map((value) => ({ value, label: formatPayerType(value) })) },
      { id: 'source', label: 'Source types', values: values.source,
        options: sources.map((value) => ({ value, label: value })) },
    ]} />
}
