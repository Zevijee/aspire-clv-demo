import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { TabFilterBar } from '../../../shared/components/filters/TabFilterBar'
import { getAdmissionsFilterOptions, formatPayerType, type AdmissionsFilterOptions } from '../api/admissions'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'
import { getLocationLevel } from '../utils/admissionsOverviewFilters'

const payers = ['Medicare', 'Medicare Advantage', 'Medicare HMO', 'Managed Medicaid', 'Medicaid', 'Hospice', 'Private Pay']

export function NetChangeFilters() {
  const [params, setParams] = useSearchParams()
  const [attempt, setAttempt] = useState(0)
  const [response, setResponse] = useState<{ attempt: number; data?: AdmissionsFilterOptions; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getAdmissionsFilterOptions().then(
      data => { if (active) setResponse({ attempt, data }) },
      () => { if (active) setResponse({ attempt, error: 'Location options could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [attempt])
  const result = response?.attempt === attempt ? response : null
  const locations = params.getAll('net_location')
  return <TabFilterBar ariaLabel="Net change filters"
    settings={{ level: [params.get('net_level') ?? getLocationLevel(locations) ?? 'state'] }}
    onApplyFilters={draft => {
      const next = new URLSearchParams(params)
      for (const key of ['net_location', 'net_payer', 'net_scope', 'net_level']) next.delete(key)
      for (const value of draft.location ?? []) next.append('net_location', value)
      for (const value of draft.payer ?? []) next.append('net_payer', value)
      next.set('net_level', draft.level?.[0] ?? 'state')
      setParams(next)
    }} filters={[
      { id: 'payer', label: 'Payer types', values: params.getAll('net_payer'),
        options: payers.map(value => ({ value, label: formatPayerType(value) })) },
      { id: 'location', label: 'Location', values: locations, options: [],
        isApplied: params.has('net_scope'),
        renderPicker: props => <AdmissionsLocationPicker {...props} locations={result?.data?.locations ?? []} />,
        isLoading: result === null, error: result?.error, onRetry: () => setAttempt(value => value + 1) },
    ]} />
}
