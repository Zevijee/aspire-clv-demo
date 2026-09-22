import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { TabFilterBar, type TabFilterBarFilter } from '../../../shared/components/filters/TabFilterBar'
import { payerCode, payerLabel } from '../api/admissionsOverview'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import type { DischargeSelection } from '../api/dischargesOverview'
import { getDischargeLogsFilters } from '../utils/dischargeLogsFilters'
import { getLocationLevel, locationLevels, matchesLocation, type LocationLevel } from '../utils/admissionsOverviewFilters'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'

const destinations = ['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility',
  'Assisted Living', 'Community', 'Funeral Home']
const dispositions = ['Routine', 'Transfer', 'AMA', 'Expired']

export function DischargesFilters({ logs, selection, onChange }: {
  logs: boolean
  selection: DischargeSelection
  onChange: (value: DischargeSelection) => void
}) {
  const [params, setParams] = useSearchParams()
  const reference = useAdmissionsReferences()
  const rows = reference.data?.locations ?? []
  const locations = rows.map(row => ({
    state: row.state, portfolio: row.portfolio_name, region: row.region_name, facility: row.facility_name,
  }))
  const state = { isLoading: reference.loading, error: reference.error, onRetry: reference.onRetry }
  const logValues = getDischargeLogsFilters(params)
  // The logs tab stores saved facility ids; the picker speaks location paths, so
  // translate in both directions rather than filtering the table by name.
  const selectedLocations = logs
    ? (logValues['facility-id'] ?? []).flatMap(id => rows.filter(row => row.facility_id === id)
        .map(row => JSON.stringify([row.state, row.portfolio_name, row.region_name, row.facility_name])))
    : selection.locations ?? []

  const locationFilter: TabFilterBarFilter = {
    id: 'location', label: 'Location', values: selectedLocations, options: [],
    isApplied: !logs && selection.scope !== null,
    renderPicker: props => <AdmissionsLocationPicker {...props} locations={locations} />,
    ...state,
  }
  const payerFilter: TabFilterBarFilter = {
    id: 'payer', label: 'Payer types',
    values: (logs ? logValues.payer ?? [] : selection.payers).map(payerCode),
    options: (reference.data?.payerTypes ?? []).map(value => ({ value, label: payerLabel(value) })),
    ...state,
  }
  const destinationFilter: TabFilterBarFilter = {
    id: 'destination-type', label: 'Destination type',
    values: logs ? logValues['destination-type'] ?? [] : selection.destinations,
    options: destinations.map(value => ({ value, label: value })),
  }
  const dispositionFilter: TabFilterBarFilter = {
    id: 'disposition', label: 'Discharge type', values: logValues.disposition ?? [],
    options: dispositions.map(value => ({ value, label: value })),
  }

  return <TabFilterBar ariaLabel="Discharges filters"
    filters={logs ? [locationFilter, payerFilter, destinationFilter, dispositionFilter]
      : [locationFilter, payerFilter, destinationFilter]}
    settings={logs ? undefined
      : { level: [selection.groupBy ?? getLocationLevel(selection.locations ?? []) ?? 'state'] }}
    onApplyFilters={draft => {
      if (logs) {
        const next = new URLSearchParams(params)
        for (const key of [...next.keys()]) if (key.startsWith('logs_')) next.delete(key)
        for (const id of ['payer', 'destination-type', 'disposition']) {
          for (const value of draft[id] ?? []) next.append(`logs_${id}`, value)
        }
        if (draft.location?.length) {
          for (const row of rows.filter(row => matchesLocation({ state: row.state, portfolio: row.portfolio_name,
            region: row.region_name, facility: row.facility_name }, draft.location))) {
            next.append('logs_facility-id', row.facility_id)
          }
        }
        setParams(next)
      } else {
        const requested = draft.level?.[0]
        const groupBy = locationLevels.find(level => level === requested)
          ?? getLocationLevel(draft.location ?? []) ?? 'state'
        // Applying a new location set clears any drill-down: the old scope may
        // not exist inside the new selection.
        onChange({ scope: null, locations: draft.location ?? [], groupBy: groupBy as LocationLevel,
          payers: draft.payer ?? [], destinations: draft['destination-type'] ?? [] })
      }
    }} />
}
