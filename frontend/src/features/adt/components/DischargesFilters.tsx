import { useEffect, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { TabFilterBar, type TabFilterBarFilter } from '../../../shared/components/filters/TabFilterBar'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getDischarges, getDischargeOverview, type DischargeFacilityMetrics } from '../api/discharges'
import { getDischargeLogsFilters } from '../utils/dischargeLogsFilters'
import { AdmissionsLocationPicker } from './AdmissionsLocationPicker'
import { matchesLocation, getLocationLevel } from '../utils/admissionsOverviewFilters'
import type { DischargeSelection } from './DischargesOverview'

const labels: Record<string, string> = {
  state: 'State', portfolio: 'Portfolio', region: 'Region', facility_name: 'Facility',
  payer_type: 'Payer type', payer_name: 'Payer name', destination_type: 'Destination type',
  destination_name: 'Destination name', discharge_type: 'Discharge type', resident_name: 'Resident',
}

export function DischargesFilters({ logs, selection, onChange }: {
  logs: boolean; selection: DischargeSelection; onChange: (value: DischargeSelection) => void
}) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const start = params.get('start_date') ?? defaults.startDate
  const end = params.get('end_date') ?? defaults.endDate
  const [attempt, setAttempt] = useState(0)
  const key = JSON.stringify([start, end, attempt])
  const [response, setResponse] = useState<{ key: string; options?: Record<string, string[]>; locations?: DischargeFacilityMetrics[]; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([
      getDischarges(start, end, 0, { filters: {}, sort: null }, false, controller.signal),
      getDischargeOverview(start, end, controller.signal),
    ]).then(([page, overview]) => {
      if (!controller.signal.aborted) setResponse({ key, options: page.filter_options, locations: overview.items })
    }).catch(() => { if (!controller.signal.aborted) setResponse({ key, error: 'Discharge filter options could not load. Please try again.' }) })
    return () => controller.abort()
  }, [start, end, key])
  const result = response?.key === key ? response : null
  const keys = logs ? Object.keys(labels) : ['payer_type', 'destination_type']
  const values = logs ? getDischargeLogsFilters(params) : {
    state: selection.path.slice(0, 1), portfolio: selection.path.slice(1, 2), region: selection.path.slice(2, 3),
    payer_type: selection.payers, destination_type: selection.destinations,
  }
  const filters: TabFilterBarFilter[] = keys.map((id) => ({
    id, label: labels[id], values: values[id] ?? [],
    options: (result?.options?.[id] ?? []).map((value) => ({ value, label: value })),
    isLoading: result === null, error: result?.error, onRetry: () => setAttempt((value) => value + 1),
  }))
  const locationRows = (result?.locations ?? []).map((row) => ({ ...row, facility: row.facility_name }))
  const locationValues = logs ? (values.facility_name ?? []).flatMap((name) => locationRows.filter((row) => row.facility === name).map((row) => JSON.stringify([row.state, row.portfolio, row.region, row.facility]))) : selection.locations ?? []
  const locationFilter: TabFilterBarFilter = {
    id: 'location', label: 'Location', values: locationValues, options: [],
    renderPicker: (props) => <AdmissionsLocationPicker {...props} locations={locationRows} />,
    isLoading: result === null, error: result?.error, onRetry: () => setAttempt((value) => value + 1),
  }
  return <TabFilterBar ariaLabel="Discharges filters" filters={[locationFilter, ...filters.filter((filter) => !['state', 'portfolio', 'region', 'facility_name'].includes(filter.id))]}
    settings={logs ? undefined : { level: [selection.groupBy ?? getLocationLevel(selection.locations ?? []) ?? 'state'] }}
    onApplyFilters={(draft) => {
      if (logs) {
        const next = new URLSearchParams(params)
        for (const id of keys) {
          next.delete(`logs_${id}`)
          for (const value of draft[id] ?? []) next.append(`logs_${id}`, value)
        }
        for (const id of ['state', 'portfolio', 'region', 'facility_name']) next.delete(`logs_${id}`)
        if (draft.location?.length) for (const row of locationRows.filter((row) => matchesLocation(row, draft.location))) next.append('logs_facility_name', row.facility)
        setParams(next)
      } else {
        onChange({ path: [], locations: draft.location ?? [], groupBy: (draft.level?.[0] ?? 'state') as DischargeSelection['groupBy'],
          payers: draft.payer_type ?? [], destinations: draft.destination_type ?? [] })
      }
    }} />
}
