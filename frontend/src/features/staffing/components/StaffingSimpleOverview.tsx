import { StaffingSectionReport, type SectionMetric } from './StaffingSectionReport'

// The hours that make up the total, against budget, with orientation beside
// them; then HPPD against budget.
const metrics: SectionMetric[] = [
  ['simple_regular_hours', 'Regular', 'hours', undefined, 'Hours'],
  ['overtime_hours', 'Overtime', 'hours', undefined, 'Hours'],
  ['agency_hours', 'Agency', 'hours', undefined, 'Hours'],
  ['hours_worked', 'Total', 'hours', undefined, 'Hours'],
  ['target_hours', 'Budget', 'hours', undefined, 'Hours'],
  ['hours_vs_budget', 'Variance', 'signedHours', 'neutral', 'Hours'],
  ['orientation_hours', 'Orientation', 'hours', undefined, 'Hours'],
  ['hppd', 'HPPD', 'hppd', undefined, 'HPPD'],
  ['hppd_budget', 'Budget', 'hppd', undefined, 'HPPD'],
  ['hppd_vs_budget', 'Variance', 'variance', 'neutral', 'HPPD'],
]

/** The Staffing Overview's Simple overview tab, its first: hours worked and their
 * budget, and HPPD against its budget, by location and by role. The figures are
 * the Full overview's own, and as there an Overtime figure opens the employees
 * with overtime behind it and a role's name the Employees tab. */
export function StaffingSimpleOverview() {
  return <StaffingSectionReport name="Staffing" metrics={metrics}
    describe={(roleNames, range) => `Hours worked, ${roleNames}, ${range}. Overtime is hours over 40 a week per `
      + `employee and agency the hours worked by agency employees; regular is the rest, so the three add up to the `
      + `total. The budget is the target hours, each day's target HPPD times its census, and the variance the total `
      + `against it. Orientation is paid on top of the hours worked and is not in HPPD. HPPD is the hours worked over `
      + `census days, against the budget's HPPD.`}
    roleNote="Each department's hours over the facilities shown, followed by its roles."
    overtimeLinks={['overtime_hours']} />
}
