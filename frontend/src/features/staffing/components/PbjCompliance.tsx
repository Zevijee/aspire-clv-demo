import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { LocationNavigation, locationColumn } from '../../../shared/components/LocationNavigation'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import {
  drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow,
} from '../../../shared/utils/locationDrilldown'
import { getPbj, type FacilityPbj, type PbjReport } from '../api'
import { formatMeasure as format } from '../laborCost'
import { perRow } from '../perRow'
import { selectedPbjQuarter } from '../pbjQuarters'

type Row = DrilldownRow<FacilityPbj>

// Four or more days in a quarter with residents and no RN hours give a one-star
// staffing rating on Care Compare.
const NO_RN_DAYS_LIMIT = 4
// PBJ's job titles for the codes CMS's nurse staffing measures read, and the administrator.
const JOB_TITLES: [code: number, title: string][] = [
  [1, 'Administrator'],
  [5, 'Registered Nurse Director of Nursing'],
  [6, 'Registered Nurse with Administrative Duties'],
  [7, 'Registered Nurse'],
  [8, 'Licensed Practical Nurse with Administrative Duties'],
  [9, 'Licensed Practical Nurse'],
  [10, 'Certified Nurse Aide'],
  [11, 'Nurse Aide in Training'],
  [12, 'Medication Aide/Technician'],
]
const isNurse = (code: number) => code >= 5 && code <= 12
const isRn = (code: number) => code >= 5 && code <= 7

type Sums = {
  residentDays: number; weekendResidentDays: number; nurse: number; rn: number; weekendNurse: number
  agencyNurse: number; withoutRn: number; under8: number; flagged: number; facilities: number; turnover: number[]
}

/** A row's facilities summed before anything is divided. */
function sum(facilities: FacilityPbj[], codes: Record<string, number>): Sums {
  const sums: Sums = { residentDays: 0, weekendResidentDays: 0, nurse: 0, rn: 0, weekendNurse: 0, agencyNurse: 0,
    withoutRn: 0, under8: 0, flagged: 0, facilities: facilities.length, turnover: [0, 0, 0, 0, 0, 0, 0] }
  for (const facility of facilities) {
    sums.residentDays += facility.resident_days
    sums.weekendResidentDays += facility.weekend_resident_days
    sums.withoutRn += facility.days_without_rn
    sums.under8 += facility.days_under_8_rn
    if (facility.days_without_rn >= NO_RN_DAYS_LIMIT) sums.flagged += 1
    facility.turnover.forEach((value, index) => { sums.turnover[index] += value })
    for (const [role, [hours, weekendHours, agencyHours]] of Object.entries(facility.roles)) {
      const code = codes[role]
      if (!isNurse(code)) continue
      sums.nurse += hours
      sums.weekendNurse += weekendHours
      sums.agencyNurse += agencyHours
      if (isRn(code)) sums.rn += hours
    }
  }
  return sums
}

const perDay = (hours: number, days: number) => days > 0 ? hours / days : '—'
const rate = (left: number, start: number, end: number) => start + end > 0 ? left / ((start + end) / 2) * 100 : '—'
const percent = (value: number | string) => typeof value === 'number' ? `${value.toFixed(1)}%` : value
const hppd = (value: number | string) => typeof value === 'number' ? value.toFixed(2) : value

/** PBJ Compliance: each location's nurse staffing for one Payroll-Based Journal
 * quarter, as CMS reads the submission for Care Compare -- hours per resident day
 * (total nurse, RN and weekend), days without an RN and with fewer than 8 RN
 * hours, 12-month turnover and the agency share -- drilled from state to
 * facility, with the facilities at risk of a one-star staffing rating; and below,
 * the hours by PBJ job title code, employee and agency, over the facilities shown. */
export function PbjCompliance() {
  const [params, setParams] = useReportSearchParams()
  const quarter = selectedPbjQuarter(params)
  // One drill= per level, in order.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(level => updated.append('drill', level))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  const [response, setResponse] = useState<{ key: string; data: PbjReport } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    getPbj(quarter.start, quarter.end, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: quarter.value, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setFailure({ key: quarter.value, message: error.message }) })
    return () => controller.abort()
  }, [quarter.start, quarter.end, quarter.value, retry])
  const data = response?.key === quarter.value ? response.data : null
  const error = failure?.key === quarter.value ? failure.message : null
  const loading = !data && !error
  const onRetry = () => setRetry(count => count + 1)
  const codes = data?.codes ?? {}

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // Each row's sums once, however many columns and sorts ask.
  const sums = perRow((row: Row) => sum(row.facilities, codes))
  const columns: TableColumn<Row>[] = [
    locationColumn<FacilityPbj>(depth, path, setPath),
    { id: 'resident_days', header: 'Resident days', group: 'Census', numeric: true, value: row => sums(row).residentDays,
      format: value => format(value, 'count') },
    { id: 'nurse', header: 'Total nurse', group: 'Hours per resident day', numeric: true,
      value: row => perDay(sums(row).nurse, sums(row).residentDays), format: hppd },
    { id: 'rn', header: 'RN', group: 'Hours per resident day', numeric: true,
      value: row => perDay(sums(row).rn, sums(row).residentDays), format: hppd },
    { id: 'weekend', header: 'Weekend total nurse', group: 'Hours per resident day', numeric: true,
      value: row => perDay(sums(row).weekendNurse, sums(row).weekendResidentDays), format: hppd },
    { id: 'without_rn', header: 'Days without RN', group: 'RN coverage', numeric: true,
      value: row => sums(row).withoutRn, format: value => format(value, 'count') },
    { id: 'under_8', header: 'Days under 8 RN hours', group: 'RN coverage', numeric: true,
      value: row => sums(row).under8, format: value => format(value, 'count') },
    { id: 'nurse_turnover', header: 'Total nurse', group: 'Turnover, 12 months', numeric: true,
      value: row => rate(sums(row).turnover[0], sums(row).turnover[1], sums(row).turnover[2]), format: percent },
    { id: 'rn_turnover', header: 'RN', group: 'Turnover, 12 months', numeric: true,
      value: row => rate(sums(row).turnover[3], sums(row).turnover[4], sums(row).turnover[5]), format: percent },
    { id: 'administrators', header: 'Administrators left', group: 'Turnover, 12 months', numeric: true,
      value: row => sums(row).turnover[6], format: value => format(value, 'count') },
    { id: 'agency', header: 'Agency share', group: 'Contract staff', numeric: true,
      value: row => sums(row).nurse > 0 ? sums(row).agencyNurse / sums(row).nurse * 100 : '—', format: percent },
    { id: 'flagged', header: 'One-star risk', group: 'Care Compare', numeric: true, value: row => sums(row).flagged,
      format: (value, row) => sums(row).facilities === 1 ? (Number(value) > 0 ? 'Yes' : 'No')
        : `${format(value, 'count')} of ${format(sums(row).facilities, 'count')}` },
  ]

  const due = dayjs(quarter.due)
  const daysLeft = due.diff(dayjs().startOf('day'), 'day')
  const deadline = daysLeft > 0 ? `due ${due.format('MMMM D, YYYY')}, in ${daysLeft} days`
    : daysLeft === 0 ? 'due today' : `was due ${due.format('MMMM D, YYYY')}`
  const subtitle = `${quarter.label}: the PBJ submission ${deadline}, 45 days after the quarter ends. Hours per resident `
    + 'day are reported hours over resident days (each day\'s closing census), not case-mix adjusted: total nurse is RN, '
    + 'LPN and nurse aide hours (PBJ codes 5-12), RN codes 5-7, weekend the same over Saturdays and Sundays; agency and '
    + 'contract hours are included, as PBJ reports them. Days without an RN have residents and no RN hours; '
    + `${NO_RN_DAYS_LIMIT} or more in a quarter give a one-star staffing rating on Care Compare. Days under 8 RN hours `
    + 'stand in for the rule of an RN 8 consecutive hours a day, which daily totals cannot show. Turnover is the '
    + 'facility\'s own nurses who left in the 12 months to the quarter\'s end, over their average headcount.'
  const file = quarter.value

  // The job title table covers the facilities the drilldown shows.
  const scoped = rows.flatMap(row => row.facilities)
  const residentDays = scoped.reduce((total, facility) => total + facility.resident_days, 0)
  type TitleRow = { code: number; title: string; employee: number; agency: number; isTotal?: boolean }
  const titleRows: TitleRow[] = JOB_TITLES.map(([code, title]) => {
    let employee = 0
    let agency = 0
    for (const facility of scoped) {
      for (const [role, [hours, , agencyHours]] of Object.entries(facility.roles)) {
        if (codes[role] !== code) continue
        employee += hours - agencyHours
        agency += agencyHours
      }
    }
    return { code, title, employee, agency }
  })
  const titleColumns: TableColumn<TitleRow>[] = [
    { id: 'code', header: 'PBJ code', isRowHeader: true, value: row => row.isTotal ? '' : row.code,
      format: (_, row) => row.isTotal ? 'Total' : String(row.code) },
    // The whole title: PBJ's names are what a submission is checked against.
    { id: 'title', header: 'Job title', truncate: false, value: row => row.title },
    { id: 'employee', header: 'Employee hours', numeric: true, value: row => row.employee, format: value => format(value, 'hours') },
    { id: 'agency', header: 'Agency hours', numeric: true, value: row => row.agency, format: value => format(value, 'hours') },
    { id: 'total', header: 'Total hours', numeric: true, value: row => row.employee + row.agency,
      format: value => format(value, 'hours') },
    { id: 'hppd', header: 'Hours per resident day', numeric: true,
      value: row => perDay(row.employee + row.agency, residentDays), format: hppd },
  ]
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} PBJ compliance`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={onRetry}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities"
        onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`pbj-compliance-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · PBJ compliance, ${quarter.label}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={onRetry}
      csvFileName={`pbj-compliance-facilities-${file}.csv`} />
    <Table<TitleRow> title="Hours by PBJ job title" columns={titleColumns} rows={titleRows}
      getRowKey={row => String(row.code)}
      // The nurse staffing codes together, as CMS adds them up: the administrator is not one of them.
      getFooterRow={visible => {
        const nurses = visible.filter(row => isNurse(row.code))
        return { code: 0, title: 'Total nurse staffing (codes 5-12)', isTotal: true,
          employee: nurses.reduce((total, row) => total + row.employee, 0),
          agency: nurses.reduce((total, row) => total + row.agency, 0) }
      }}
      loading={loading} error={error} onRetry={onRetry}
      subtitle={`${scopeName} · ${quarter.label}. Each PBJ job title's hours over the facilities shown, the facility's `
        + 'own employees and agency or contract staff, as PBJ reports them, and per resident day. The roster has no '
        + 'Director of Nursing role, so code 5 has no hours: a full-time RN DON is required, and PBJ reports one.'}
      emptyMessage="No hours in this quarter."
      csvFileName={`pbj-job-titles-${file}.csv`} />
  </>
}
