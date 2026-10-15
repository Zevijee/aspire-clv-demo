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
import { getStaffingOverview, STAFFING_ROLES, type FacilityOverview, type RoleOverview, type StaffingOverview as Report } from '../api'
import { useDrilldownRoles } from './DrilldownRoleFilter'
import { useStaffingDrillLinks } from '../drillLinks'
import { departmentSections, type RoleRow as DepartmentRoleRow } from '../departmentSections'
import { formatMeasure as format, laborCost, type MeasureKind, type Premiums } from '../laborCost'

type Row = DrilldownRow<FacilityOverview>
type RoleRow = DepartmentRoleRow<FacilityOverview>
type Kind = MeasureKind
type Measure = keyof RoleOverview

// In sections: census, HPPD/PPD, hours, hourly rates and cost first, then
// agency, overtime and the premiums they add, then orientation and training.
const metrics: [id: string, header: string, kind: Kind, group?: string][] = [
  ['census_days', 'Total census days', 'count', 'Census'],
  ['census', 'Avg. daily census', 'average', 'Census'],
  ['hppd', 'HPPD', 'hppd', 'HPPD/PPD'],
  ['hppd_budget', 'HPPD budget', 'hppd', 'HPPD/PPD'],
  ['hppd_vs_budget', 'HPPD vs budget', 'variance', 'HPPD/PPD'],
  ['ppd', 'PPD cost', 'rate', 'HPPD/PPD'],
  ['ppd_budget', 'PPD budget', 'rate', 'HPPD/PPD'],
  ['ppd_vs_budget', 'PPD vs budget', 'signedRate', 'HPPD/PPD'],
  ['regular_hours', 'Regular hours', 'hours', 'Hours'],
  ['hours_overtime', 'Overtime hours', 'hours', 'Hours'],
  ['holiday_hours', 'Holiday hours', 'hours', 'Hours'],
  ['hours_agency', 'Agency hours', 'hours', 'Hours'],
  ['hours_training', 'Training hours', 'hours', 'Hours'],
  ['hours_classroom_orientation', 'Classroom orientation hours', 'hours', 'Hours'],
  ['hours_floor_orientation', 'Floor orientation hours', 'hours', 'Hours'],
  ['total_hours', 'Total hours', 'hours', 'Hours'],
  ['rate', 'Avg. hourly rate', 'rate', 'Hourly rate'],
  ['regular_rate', 'Regular rate', 'rate', 'Hourly rate'],
  ['rate_overtime', 'Overtime rate', 'rate', 'Hourly rate'],
  ['holiday_rate', 'Holiday rate', 'rate', 'Hourly rate'],
  ['rate_agency', 'Agency rate', 'rate', 'Hourly rate'],
  ['regular_pay', 'Regular pay', 'money', 'Cost'],
  ['overtime_pay', 'Overtime pay', 'money', 'Cost'],
  ['holiday_pay', 'Holiday pay', 'money', 'Cost'],
  ['agency_pay', 'Agency pay', 'money', 'Cost'],
  ['training_pay', 'Training pay', 'money', 'Cost'],
  ['classroom_orientation_pay', 'Classroom orientation pay', 'money', 'Cost'],
  ['floor_orientation_pay', 'Floor orientation pay', 'money', 'Cost'],
  ['cost_bonuses', 'Bonuses', 'money', 'Cost'],
  ['total_cost', 'Total cost', 'money', 'Cost'],
  ['agency_hours', 'Agency hours', 'hours', 'Agency vs In-house'],
  ['inhouse_hours', 'In-house hours', 'hours', 'Agency vs In-house'],
  ['agency_share', 'Agency share', 'share', 'Agency vs In-house'],
  ['agency_rate', 'Agency rate', 'rate', 'Agency vs In-house'],
  ['agency_premium', 'Agency premium', 'money', 'Agency vs In-house'],
  ['overtime_hours', 'Overtime hours', 'hours', 'Overtime'],
  ['straight_hours', 'Straight-time hours', 'hours', 'Overtime'],
  ['overtime_share', 'Overtime share', 'share', 'Overtime'],
  ['overtime_rate', 'Overtime rate', 'rate', 'Overtime'],
  ['overtime_premium', 'Overtime premium', 'money', 'Overtime'],
  ['excess_spend', 'Overbudget excess spend', 'money', 'Premiums and extras'],
  ['premium_agency', 'Agency premium', 'money', 'Premiums and extras'],
  ['premium_overtime', 'Overtime premium', 'money', 'Premiums and extras'],
  ['total_premiums', 'Total premiums', 'money', 'Premiums and extras'],
  ['classroom_orientation_hours', 'Classroom orientation hours', 'hours', 'Orientation'],
  ['floor_orientation_hours', 'Floor orientation hours', 'hours', 'Orientation'],
  ['orientation_hours', 'Total orientation hours', 'hours', 'Orientation'],
  ['classroom_days', 'Avg. classroom days', 'average', 'Orientation'],
  ['floor_days', 'Avg. floor days', 'average', 'Orientation'],
  ['orientation_days', 'Avg. total days', 'average', 'Orientation'],
  ['orientation_classroom_cost', 'Classroom orientation cost', 'money', 'Orientation'],
  ['orientation_floor_cost', 'Floor orientation cost', 'money', 'Orientation'],
  ['orientation_cost', 'Total orientation cost', 'money', 'Orientation'],
  ['training_hours', 'Training hours', 'hours', 'Training'],
  ['training_share', 'Training share', 'share', 'Training'],
  ['training_cost', 'Training cost', 'money', 'Training'],
]
// Columns that repeat another section's figure, under an id of their own: a
// table's column ids are unique, so each points at the figure it repeats.
const SAME_AS: Record<string, string> = {
  hours_overtime: 'overtime_hours', hours_agency: 'agency_hours', hours_training: 'training_hours',
  hours_classroom_orientation: 'classroom_orientation_hours', hours_floor_orientation: 'floor_orientation_hours',
  orientation_classroom_cost: 'classroom_orientation_pay', orientation_floor_cost: 'floor_orientation_pay',
  training_cost: 'training_pay',
  cost_bonuses: 'bonuses', rate_overtime: 'overtime_rate',
  rate_agency: 'agency_rate', premium_agency: 'agency_premium', premium_overtime: 'overtime_premium',
}

// How each signed column is coloured: the gaps between actual and the lowest
// possible show their plus sign in green; HPPD against budget is neither good
// nor bad either way, so it stays uncoloured.
const CHANGES: Record<string, 'increase' | 'neutral'> = {
  hppd_vs_budget: 'neutral', ppd_vs_budget: 'increase',
}

/** One section of the Overview's columns, with their headers and colouring, for
 * a report that shows that section on its own (StaffingSectionReport). */
export function overviewSection(group: string): [id: string, header: string, kind: Kind, change?: 'increase' | 'neutral'][] {
  return metrics.filter(([, , , section]) => section === group).map(([id, header, kind]) => [id, header, kind, CHANGES[id]])
}

// The figures shown with their share of a total after them -- "1,431,267, 90.8%" --
// and the total each is a share of: the kinds of hour of total hours, the kinds
// of pay of total cost.
const SHARE_OF: Record<string, 'totalHours' | 'totalCost'> = {
  regular_hours: 'totalHours', hours_overtime: 'totalHours', holiday_hours: 'totalHours', hours_agency: 'totalHours',
  hours_training: 'totalHours', hours_classroom_orientation: 'totalHours', hours_floor_orientation: 'totalHours',
  regular_pay: 'totalCost', overtime_pay: 'totalCost', holiday_pay: 'totalCost', agency_pay: 'totalCost',
  training_pay: 'totalCost', classroom_orientation_pay: 'totalCost', floor_orientation_pay: 'totalCost',
  cost_bonuses: 'totalCost',
}

/** A cell's text: the figure, and for a kind of hour or pay its share of the
 * total after it, set smaller and lighter. Sorting and the CSV keep the figure alone. */
export function formatMetric(id: string, kind: Kind, value: number | string, row: Row, days: number,
  premiums: Premiums, roles: string[]) {
  const text = format(value, kind)
  if (!SHARE_OF[id] || typeof value !== 'number') return text
  const share = metric(row, `share_of_${id}`, days, premiums, roles)
  return share === null ? text : <>{text}, <span className="staffing-share">{format(share, 'share')}</span></>
}

/** The hires who took orientation: those of the roles with any orientation
 * hours at this scope. Only Direct Care orients, so the average days are over
 * the people who did it, never diluted by every other department's hires. */
function orientedHires(row: Row, roles: string[]) {
  let hires = 0
  for (const code of roles) {
    let hours = 0, roleHires = 0
    for (const facility of row.facilities) {
      const role = facility.roles[code]
      if (!role) continue
      hours += role.classroom_orientation_hours + role.floor_orientation_hours
      roleHires += role.new_hires
    }
    if (hours > 0) hires += roleHires
  }
  return hires
}

// The Overtime section's Overtime hours: a figure opens the shifts behind it.
const OVERTIME_LINKS = new Set(['overtime_hours'])

// Summed at this scope, then divided once: never an average of facility rates.
// The cost arithmetic is shared with the PPD report (laborCost); the Training
// and Orientation reports show these same figures (StaffingSectionReport).
export function metric(row: Row, column: string, days: number, premiums: Premiums, roles: string[]): number | null {
  // A kind of hour's or pay's share of its total: its own figure over the total, each summed first.
  if (column.startsWith('share_of_')) {
    const of = column.slice('share_of_'.length)
    const value = metric(row, of, days, premiums, roles)
    const total = laborCost(row.facilities, roles, premiums)[SHARE_OF[of] ?? 'totalHours']
    return value !== null && total > 0 ? value / total : null
  }
  const id = SAME_AS[column] ?? column
  const cost = laborCost(row.facilities, roles, premiums)
  const { censusDays, totalHours, totalCost, overtimePremium, holidayPremium, orientationHours, orientationCost } = cost
  const n = (key: Measure) => cost.sums[key] ?? 0
  const perCensusDay = (value: number) => censusDays > 0 ? value / censusDays : null
  const rate = totalHours > 0 ? totalCost / totalHours : null
  switch (id) {
    case 'census': return days > 0 ? censusDays / days : null
    case 'census_days': return censusDays
    case 'hppd': return perCensusDay(n('hours'))
    case 'hppd_budget': return perCensusDay(n('target_hours'))
    case 'hppd_vs_budget': return perCensusDay(n('hours') - n('target_hours'))
    case 'classroom_orientation_hours': return n('classroom_orientation_hours')
    case 'floor_orientation_hours': return n('floor_orientation_hours')
    case 'new_hires': return n('new_hires')
    // The Simple overview's hours: total hours worked, the regular rest of them
    // after overtime and agency, so the three add up to the total, and the
    // total against its budget, the target hours.
    case 'hours_worked': return n('hours')
    case 'simple_regular_hours': return n('hours') - n('overtime_hours') - n('agency_hours')
    case 'target_hours': return n('target_hours')
    case 'hours_vs_budget': return n('hours') - n('target_hours')
    case 'orientation_hours': return orientationHours
    case 'orientation_cost': return orientationCost
    case 'training_hours': return n('training_hours')
    // Of every paid hour, summed then divided.
    case 'training_share': return totalHours > 0 ? n('training_hours') / totalHours : null
    // Days from the hire date, summed over the hires and divided once by them;
    // floor follows classroom, so both is the two added.
    case 'classroom_days':
    case 'floor_days':
    case 'orientation_days': {
      const hires = orientedHires(row, roles)
      const daysTaken = (id === 'floor_days' ? 0 : n('classroom_orientation_days'))
        + (id === 'classroom_days' ? 0 : n('floor_orientation_days'))
      return hires > 0 ? daysTaken / hires : null
    }
    // Each kind's pay: its hours at straight time, with its premium where it has one.
    case 'regular_pay': return n('wages') - n('overtime_wages') - n('holiday_wages')
    case 'overtime_pay': return n('overtime_wages') + overtimePremium
    case 'holiday_pay': return n('holiday_wages') + holidayPremium
    case 'agency_pay': return n('agency_wages')
    case 'training_pay': return n('training_wages')
    case 'classroom_orientation_pay': return n('classroom_orientation_wages')
    case 'floor_orientation_pay': return n('floor_orientation_wages')
    // Each kind's pay over its hours.
    case 'regular_rate': {
      const hours = n('hours') - n('overtime_hours') - n('holiday_hours')
      return hours > 0 ? (n('wages') - n('overtime_wages') - n('holiday_wages')) / hours : null
    }
    case 'holiday_rate': return n('holiday_hours') > 0 ? (n('holiday_wages') + holidayPremium) / n('holiday_hours') : null
    case 'training_rate': return n('training_hours') > 0 ? n('training_wages') / n('training_hours') : null
    case 'overtime_hours': return n('overtime_hours')
    case 'straight_hours': return n('hours') - n('overtime_hours')
    case 'overtime_share': return n('hours') > 0 ? n('overtime_hours') / n('hours') : null
    // What an overtime hour pays: its straight-time pay and the premium on it.
    case 'overtime_rate': return n('overtime_hours') > 0 ? (n('overtime_wages') + overtimePremium) / n('overtime_hours') : null
    case 'holiday_hours': return n('holiday_hours')
    case 'regular_hours': return n('hours') - n('overtime_hours') - n('holiday_hours')
    case 'agency_hours': return n('agency_hours')
    case 'inhouse_hours': return n('inhouse_hours')
    // Of the hours worked, summed then divided: never an average of shares.
    case 'agency_share': return n('hours') > 0 ? n('agency_hours') / n('hours') : null
    case 'agency_rate': return n('agency_hours') > 0 ? n('agency_wages') / n('agency_hours') : null
    case 'agency_premium': return n('agency_premium')
    case 'total_hours': return totalHours
    case 'rate': return rate
    case 'total_cost': return totalCost
    case 'ppd': return perCensusDay(totalCost)
    // The budget per patient day: the target hours at straight time, as the
    // PPD report's Budget PPD; PPD's premiums, orientation and bonuses are over it.
    case 'ppd_budget': return perCensusDay(cost.budgetCost)
    case 'ppd_vs_budget': return perCensusDay(totalCost - cost.budgetCost)
    case 'excess_spend': return n('excess_wages')
    case 'overtime_premium': return overtimePremium
    case 'bonuses': return n('bonuses')
    // The columns of the section added up.
    case 'total_premiums': return n('excess_wages') + n('agency_premium') + overtimePremium
    default: return null
  }
}

/** Staffing Overview: every role's hours and labour cost in the header's date
 * range, drilled from state to facility: census and HPPD against budget, the
 * hours by kind, what they cost and what each premium added, against the
 * lowest the same care could have cost. The drilldown is kept in the URL. */
export function StaffingOverview() {
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

  const scoped = rows.flatMap(row => row.facilities)
  // An Overtime hours figure in the Overtime section opens the employees with
  // overtime behind it; a role's or department's name, the Employees tab.
  const links = useStaffingDrillLinks({ path, grouping, scoped, roles, roleName,
    startDate: data?.start_date ?? startDate, endDate: data?.end_date ?? endDate })

  const metricColumns = metrics.map(([id, header, kind, group]): TableColumn<Row> => ({
    id, header, group, numeric: true, value: row => metric(row, id, days, premiums, roles) ?? '—',
    format: (value: number | string, row: Row) => {
      const shown = formatMetric(id, kind, value, row, days, premiums, roles)
      return OVERTIME_LINKS.has(id) && typeof value === 'number' ? links.locationOvertime(shown, row) : shown
    },
    ...(CHANGES[id] ? { change: { favorable: CHANGES[id] } } : {}),
  }))
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityOverview>(depth, path, setPath),
    ...metricColumns,
  ]
  const shownStart = data?.start_date ?? startDate
  const shownEnd = data?.end_date ?? endDate
  const range = `${shownStart} to ${shownEnd}`
  const holidayCount = data?.holidays.length ?? 0
  const describe = (roleNames: string) => `${roleNames}, ${range}. Avg. daily census is total census days over the days in the range, and total census days each day's closing census summed; HPPD is hours worked per census day, `
    + 'the HPPD budget is the target, and HPPD vs budget the difference. Regular, overtime and holiday hours make up hours worked; '
    + 'orientation, in the classroom and on the floor shadowing a preceptor, and in-service training are paid on '
    + 'top of them and are not in HPPD, so total hours are hours worked plus training and orientation. After each kind of '
    + "hour is its share of total hours, and after each kind of pay its share of total cost; training share is training's part of them, "
    + 'and the orientation and training costs their pay. '
    + 'The days to finish are the average calendar days from a hire date to the end of classroom orientation, of floor '
    + "orientation, which follows it, and of both; each hire's orientation and its cost are counted on the hire date. "
    + `Overtime is hours over 40 a week per employee, straight-time hours the rest of the hours worked, the overtime `
    + `rate what an overtime hour pays with its premium; holiday hours are the rest of the hours worked on ${holidayCount} `
    + `paid holiday${holidayCount === 1 ? '' : 's'} in the range. Agency hours are the hours worked by agency employees, `
    + 'of any kind; agency share is their part of the hours worked, the agency rate their pay over their hours, '
    + 'and the agency premium what they cost over the in-house rate. Total cost is straight-time pay plus the agency, overtime and holiday premiums, orientation, training and '
    + `bonuses; overtime and holiday hours pay ${premiums.overtime * 100}% over straight time. The average hourly `
    + 'rate is total cost over total hours. Overbudget excess spend is the hours over each day\'s budget at '
    + 'straight time. The PPD columns are the cost columns per census day; the PPD budget is the target hours at straight time per census day, and PPD vs budget the difference. Total '
    + 'premiums adds up the excess spend and the agency and overtime premiums. The Hours, Cost and Hourly rate sections repeat each kind of hour, its pay and its rate; agency hours '
    + 'and pay are part of the others, for reference.'
  const subtitle = describe(roleName.charAt(0).toUpperCase() + roleName.slice(1))
  const file = `${shownStart}-to-${shownEnd}`

  // The role tables follow the drilldown and custom grouping, as the table
  // does: one row per role with its totals over the facilities shown. Census
  // is the same for every role, so the role tables leave it out.
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const roleRows: RoleRow[] = STAFFING_ROLES
    .map(role => ({ key: role.value, name: role.label, path: [], facilities: scoped, codes: [role.value] }))
  const roleColumns: TableColumn<RoleRow>[] = [
    { id: 'name', header: 'Role', value: row => row.name, isRowHeader: true, format: (_, row) => links.roleName(row) },
    ...metrics.filter(([id]) => id !== 'census' && id !== 'census_days').map(([id, header, kind, group]): TableColumn<RoleRow> => ({
      id, header, group, numeric: true, value: row => metric(row, id, days, premiums, row.codes) ?? '—',
      format: (value: number | string, row: RoleRow) => {
        const shown = formatMetric(id, kind, value, row, days, premiums, row.codes)
        return OVERTIME_LINKS.has(id) && typeof value === 'number' ? links.roleOvertime(shown, row) : shown
      },
      ...(CHANGES[id] ? { change: { favorable: CHANGES[id] } } : {}),
    })),
  ]

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} staffing`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      filters={roleFilter}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`staffing-overview-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)} filters={roleFilter}
      onSelect={next => setPath(next)}
      title={`All facilities · Staffing overview, ${roleName}, ${range}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`staffing-overview-facilities-${file}.csv`} />
    <Table<RoleRow> stickyFirstColumn floatHeader title="Staffing by role" columns={roleColumns} rows={roleRows}
      sections={departmentSections(scoped)}
      // Every role over the facilities shown, summed and divided once.
      getFooterRow={visible => ({ key: 'total', name: 'All roles', path: [], isTotal: true, facilities: scoped,
        codes: visible.flatMap(row => row.codes) })}
      // No initial sort: the roles come in report order within each department.
      getRowKey={row => row.key}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · every role, ${range}. Each role over the facilities shown, with the columns `
        + 'above: HPPD divides by the same census days for every role. Each department is followed by its roles.'}
      emptyMessage="No roles match this view."
      csvFileName={`staffing-overview-roles-${file}.csv`} />
    {links.modal}
  </>
}
