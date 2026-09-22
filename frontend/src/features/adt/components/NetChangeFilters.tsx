import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { TabFilterBar, type TabFilterBarFilter } from '../../../shared/components/filters/TabFilterBar'
import { payerCode, payerLabel } from '../api/admissionsOverview'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { getLocationLevel, locationLevels } from '../utils/admissionsOverviewFilters'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'

export function NetChangeFilters() {
  const [params, setParams] = useSearchParams()
  const reference = useAdmissionsReferences()
  const rows = reference.data?.locations ?? []
  const locations = rows.map(row => ({
    state: row.state, portfolio: row.portfolio_name, region: row.region_name, facility: row.facility_name,
  }))
  const state = { isLoading: reference.loading, error: reference.error, onRetry: reference.onRetry }
  const selectedLocations = params.getAll('net_location')
  const selectedPayers = params.getAll('net_payer').map(payerCode)
  const level = locationLevels.find(value => value === params.get('net_level'))
    ?? getLocationLevel(selectedLocations) ?? 'state'

  const filters: TabFilterBarFilter[] = [
    { id: 'location', label: 'Location', values: selectedLocations, options: [],
      isApplied: params.getAll('net_scope').length > 0,
      renderPicker: props => <AdmissionsLocationPicker {...props} locations={locations} />,
      ...state },
    { id: 'payer', label: 'Payer types', values: selectedPayers,
      options: (reference.data?.payerTypes ?? []).map(value => ({ value, label: payerLabel(value) })),
      ...state },
  ]
  return <TabFilterBar ariaLabel="Net change filters" filters={filters}
    settings={{ level: [level] }}
    onApplyFilters={draft => {
      const next = new URLSearchParams(params)
      // Applying a new location set clears any drill-down: the old scope may not
      // exist inside the new selection.
      for (const key of ['net_location', 'net_payer', 'net_level', 'net_scope']) next.delete(key)
      const requested = draft.level?.[0]
      const groupBy = locationLevels.find(value => value === requested)
        ?? getLocationLevel(draft.location ?? []) ?? 'state'
      next.set('net_level', groupBy)
      for (const value of draft.location ?? []) next.append('net_location', value)
      for (const value of draft.payer ?? []) next.append('net_payer', value)
      setParams(next)
    }} />
}
