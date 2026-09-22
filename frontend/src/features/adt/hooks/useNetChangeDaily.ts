import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { payerCode } from '../api/admissionsOverview'
import { netChangeParameters, type NetChangeSelection } from '../api/netChangeOverview'
import { getLocationLevel, locationLevels } from '../utils/admissionsOverviewFilters'
import { useAdmissionsReferences } from './useAdmissionsOverview'
import { useNetChangeOverview } from './useNetChangeOverview'
import type { DailyMovement } from '../components/NetChangeDayOverDay'
import type { DrilldownScope } from '../utils/admissionsDrilldown'

export type { DailyMovement }

/** Daily census movement, either from the report's URL state or an explicit range.
 *
 * The daily series is part of the overview response, so this shares that request
 * rather than calling a separate endpoint.
 */
export function useNetChangeDaily(range?: {
  startDate: string; endDate: string; payers?: string[]; path?: string[]
}) {
  const [params] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = range?.startDate ?? params.get('start_date') ?? defaults.startDate
  const endDate = range?.endDate ?? params.get('end_date') ?? defaults.endDate
  const payers = (range ? range.payers ?? [] : params.getAll('net_payer')).map(payerCode)
  const path = range ? range.path ?? [] : params.getAll('net_scope').slice(0, 4)
  const locations = range ? [] : params.getAll('net_location')

  const scope: DrilldownScope = path.length
    ? { state: path[0], portfolio: path[1], region: path[2], facility: path[3] } : null
  const requested = params.get('net_level')
  const groupBy = locationLevels.find(value => value === requested)
    ?? getLocationLevel(locations) ?? 'state'
  const selection: NetChangeSelection = { scope, payers, locations, groupBy }

  const references = useAdmissionsReferences()
  const parameters = references.data
    ? netChangeParameters(selection, references.data, groupBy).toString() : null
  const overview = useNetChangeOverview(startDate, endDate, parameters)

  const items: DailyMovement[] = (overview.data?.daily ?? []).map(row => ({
    date: row.date, value: row.net_change,
    opening_census: row.opening_census, closing_census: row.closing_census,
    admissions: row.admissions, discharges: row.discharges,
    payer_changes_in: row.payer_changes_in, payer_changes_out: row.payer_changes_out,
  }))
  return {
    items,
    loading: references.loading || overview.loading,
    error: references.error ?? overview.error,
    onRetry: references.error ? references.onRetry : overview.onRetry,
    startDate, endDate, hasPayers: payers.length > 0,
  }
}
