import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getAgency, STAFFING_ROLES, type AgencyReport, type FacilityAgency } from '../api'

type Row = DrilldownRow<FacilityAgency>
// A row of the role table: one role over the drilldown's facilities. `codes` is
// the role, or every role shown for the Total row.
type RoleRow = Row & { codes: string[] }
type Kind = 'hours' | 'rate' | 'money'

const metrics: [id: string, header: string, kind: Kind][] = [
  ['hours', 'Hours worked', 'hours'],
  ['inhouse_hours', 'In-house hours', 'hours'],
  ['agency_hours', 'Agency hours', 'hours'],
  ['inhouse_rate', 'Avg. in-house rate', 'rate'],
  ['agency_rate', 'Avg. agency rate', 'rate'],
  ['premium', 'Extra spent on agency', 'money'],
]

// The chosen roles' sums at this scope.
function sums(row: Row, roles: string[]) {
  const total = { agencyHours: 0, agencyWages: 0, inhouseHours: 0, inhouseWages: 0, premium: 0 }
  for (const facility of row.facilities) {
    for (const code of roles) {
      const role = facility.roles[code]
      if (!role) continue
      total.agencyHours += role.agency_hours
      total.agencyWages += role.agency_wages
      total.inhouseHours += role.inhouse_hours
      total.inhouseWages += role.inhouse_wages
      total.premium += role.agency_premium
    }
  }
  return total
}

// Summed at this scope, then divided once: never an average of facility rates.
// The premium is summed as the API measured it, at each facility and role,
// never recomputed from the scope's blended rates.
function metric(row: Row, id: string, roles: string[]): number | null {
  const total = sums(row, roles)
  if (id === 'hours') return total.agencyHours + total.inhouseHours
  if (id === 'inhouse_hours') return total.inhouseHours
  if (id === 'agency_hours') return total.agencyHours
  if (id === 'inhouse_rate') return total.inhouseHours > 0 ? total.inhouseWages / total.inhouseHours : null
  if (id === 'agency_rate') return total.agencyHours > 0 ? total.agencyWages / total.agencyHours : null
  return total.premium
}

function format(value: number | string, kind: Kind) {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (kind === 'money') return `$${Math.round(value).toLocaleString()}`
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}


/** Agency vs In-house: the hours worked in the header's date range, drilled from
 * state to facility, split between agency staff and the facility's own, with
 * the average rate of each and what the agency hours cost over in-house. Below
 * it, one row per role for the drilldown's scope. The drilldown is kept in the URL. */
export function AgencyDrilldown() {
  const [params, setParams] = useReportSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  // One drill= per level, in order.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [data, setData] = useState<AgencyReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  // Every role, as PPD's Overview: the table adds them all up and the role
  // table lists each. The Trending tab has the role picker.
  const roles = STAFFING_ROLES.map(role => role.value)
  const roleName = 'every role'
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getAgency(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityAgency>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id, roles) ?? '—',
      format: (value: number | string) => format(value, kind),
    })),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const subtitle = `Hours worked by agency staff and by each facility's own staff, ${roleName}, ${range}. Each average `
    + 'rate is wages over hours. Extra spent on agency is what the agency hours cost over the same hours at the '
    + `in-house rate, measured at each facility and role and added up.`
  const file = `${shownStart}-to-${shownEnd}`

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role, with that role's totals over the facilities shown,
  // each summed at this scope and divided once.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  const roleRows: RoleRow[] = STAFFING_ROLES.filter(role => roles.includes(role.value))
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true },
    ...metrics.map(([id, header, kind]): TableColumn<RoleRow> => ({
      id, header, numeric: true, value: row => metric(row, id, row.codes) ?? '—',
      format: (value: number | string) => format(value, kind),
    })),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} agency vs in-house`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`agency-vs-inhouse-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · Agency vs in-house, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`agency-vs-inhouse-facilities-${file}.csv`} />
    <DrilldownTable<RoleRow> title="Agency vs in-house by role" columns={roleColumns} rows={roleRows}
      // No initial sort: the roles come in report order, nursing, therapy, support.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      // Every role shown over the same facilities, divided once: the same
      // figures as the Total row above, never the rows added together.
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: scoped, codes: visible.map(row => row.codes[0]) })}
      subtitle={`${scopeName} · ${roleName}, ${range}. Each role's hours over the facilities shown, split by who `
        + 'worked them, with each average rate divided once. The Total row is every role shown, added up.'}
      emptyMessage="No roles match this view."
      csvFileName={`agency-vs-inhouse-roles-${file}.csv`} />
  </>
}
