import { useEffect, useState } from 'react'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
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
import { getStaffingOverview, STAFFING_ROLES, type FacilityOverview, type StaffingOverview as Report } from '../api'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { departmentSections, type RoleRow as DepartmentRoleRow } from '../departmentSections'
import { useStaffingDrillLinks } from '../drillLinks'
import { formatMeasure as format, laborCost, type MeasureKind, type Premiums } from '../laborCost'

type Row = DrilldownRow<FacilityOverview>
type RoleRow = DepartmentRoleRow<FacilityOverview>

const metrics: [id: string, header: string, kind: MeasureKind][] = [
  ['census_days', 'Census days', 'count'],
  ['adc', 'Avg. daily census', 'average'],
  ['total_cost', 'Total cost', 'money'],
  ['ppd', 'PPD', 'rate'],
  ['budget_ppd', 'Budget PPD', 'rate'],
  ['ppd_variance', 'PPD variance', 'signedRate'],
  ['straight_ppd', 'Straight-time PPD', 'rate'],
  ['agency_ppd', 'Agency premium PPD', 'rate'],
  ['overtime_ppd', 'Overtime premium PPD', 'rate'],
  ['holiday_ppd', 'Holiday premium PPD', 'rate'],
  ['orientation_ppd', 'Orientation PPD', 'rate'],
  ['training_ppd', 'Training PPD', 'rate'],
  ['bonuses_ppd', 'Bonuses PPD', 'rate'],
]
// The role table's columns: the drilldown's without the census columns, which
// are the same for every role.
const ROLE_METRICS = metrics.filter(([id]) => id !== 'census_days' && id !== 'adc')

// Summed at this scope, then divided once by the scope's census days: never an
// average of facility PPDs. The cost is the Staffing Overview's (laborCost).
function metric(row: Row, id: string, days: number, premiums: Premiums, roles: string[]): number | null {
  const cost = laborCost(row.facilities, roles, premiums)
  const perCensusDay = (value: number) => cost.censusDays > 0 ? value / cost.censusDays : null
  switch (id) {
    case 'census_days': return cost.censusDays
    case 'adc': return days > 0 ? cost.censusDays / days : null
    case 'total_cost': return cost.totalCost
    case 'ppd': return perCensusDay(cost.totalCost)
    case 'budget_ppd': return perCensusDay(cost.budgetCost)
    case 'ppd_variance': return perCensusDay(cost.totalCost - cost.budgetCost)
    case 'straight_ppd': return perCensusDay(cost.sums.wages ?? 0)
    case 'agency_ppd': return perCensusDay(cost.sums.agency_premium ?? 0)
    case 'overtime_ppd': return perCensusDay(cost.overtimePremium)
    case 'holiday_ppd': return perCensusDay(cost.holidayPremium)
    case 'orientation_ppd': return perCensusDay(cost.orientationCost)
    case 'training_ppd': return perCensusDay(cost.sums.training_wages ?? 0)
    default: return perCensusDay(cost.sums.bonuses ?? 0)
  }
}

/** PPD: labour cost per patient day over every role in the header's date range,
 * drilled from state to facility, against the budget -- the target hours at
 * straight time -- with what each part of the cost adds per patient day. Below
 * it, one row per department followed by its roles. The drilldown is kept in the URL. */
export function StaffingPpd() {
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
  const [data, setData] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getStaffingOverview(startDate, endDate, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startDate, endDate, retry])
  const onRetry = () => setRetry(count => count + 1)
  const loading = !data && !error
  const days = data?.days ?? Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86_400_000) + 1
  const premiums = { overtime: data?.overtime_premium ?? 0.5, holiday: data?.holiday_premium ?? 0.5 }

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The drilldown's roles, from its own filter; the role table lists every role.
  const { roles, roleName, filter: roleFilter } = useDrilldownRoles()
  // Over budget costs money and under it may mean short staffing: neither direction is good.
  const neutral = (id: string) => id === 'ppd_variance' ? { change: { favorable: 'neutral' as const } } : {}
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityOverview>(depth, path, setPath),
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id, days, premiums, roles) ?? '—',
      format: (value: number | string) => format(value, kind), ...neutral(id),
    })),
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const subtitle = `Labour cost per patient day, ${roleName}, ${range}. Census days are each day's closing census `
    + 'summed. Total cost is straight-time pay plus the agency, overtime and holiday premiums, orientation, training and '
    + 'bonuses, as the Staffing Overview counts it; PPD is total cost over census days. Budget PPD is the target '
    + 'hours at each facility and role\'s straight-time rate, over the same days, and PPD variance the difference. '
    + 'The last seven columns split PPD into its parts: they add up to it.'
  const file = `${shownStart}-to-${shownEnd}`

  // The role table follows the drilldown and custom grouping, as the table
  // does: one row per role with its totals over the facilities shown.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const scoped = rows.flatMap(row => row.facilities)
  // A role's or department's name opens its employees over the facilities shown.
  const links = useStaffingDrillLinks({ path, grouping, scoped, roles, roleName, startDate: shownStart, endDate: shownEnd })
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true, format: (_, row) => links.roleName(row) },
    ...ROLE_METRICS.map(([id, header, kind]): TableColumn<RoleRow> => ({
      id, header, numeric: true, value: row => metric(row, id, days, premiums, row.codes) ?? '—',
      format: (value: number | string) => format(value, kind), ...neutral(id),
    })),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} PPD`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`ppd-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · PPD, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`ppd-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title="PPD by role" columns={roleColumns} rows={roleRows}
      sections={departmentSections(scoped)}
      // Every role over the facilities shown, summed and divided once.
      getFooterRow={visible => ({ key: 'total', name: 'All roles', path: [], isTotal: true, facilities: scoped,
        codes: visible.flatMap(row => row.codes) })}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. Each department's cost over the facilities shown and their `
        + 'census days, followed by its roles.'}
      emptyMessage="No roles match this view."
      csvFileName={`ppd-roles-${file}.csv`} />
    {links.modal}
  </>
}
