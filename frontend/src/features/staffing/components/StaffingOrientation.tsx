import { StaffingSectionReport, type SectionMetric } from './StaffingSectionReport'

// The Staffing Overview's Orientation section, with the hires it is for.
const metrics: SectionMetric[] = [
  ['new_hires', 'New hires', 'count'],
  ['classroom_orientation_hours', 'Classroom hours', 'hours'],
  ['floor_orientation_hours', 'Floor hours', 'hours'],
  ['orientation_hours', 'Total hours', 'hours'],
  ['classroom_days', 'Avg. classroom days', 'average'],
  ['floor_days', 'Avg. floor days', 'average'],
  ['orientation_days', 'Avg. total days', 'average'],
  ['orientation_classroom_cost', 'Classroom cost', 'money'],
  ['orientation_floor_cost', 'Floor cost', 'money'],
  ['orientation_cost', 'Total cost', 'money'],
]

/** Orientation: the paid orientation new hires take, in the classroom and on
 * the floor shadowing a preceptor, how long it takes them to finish, and what
 * it costs, by location and by role. */
export function StaffingOrientation() {
  return <StaffingSectionReport name="Orientation" metrics={metrics}
    describe={(roleNames, range) => `Orientation of new hires, ${roleNames}, ${range}. Each Direct Care hire takes `
      + 'classroom orientation and then floor orientation, shadowing a preceptor, paid at the in-house rate; the '
      + 'other departments’ hires take none. A hire’s orientation and its cost are counted on the hire date. '
      + 'The days are the average calendar days from the hire date to the end of classroom, of floor, and of both, '
      + 'over the hires who took orientation. Orientation is paid time, not care: it is in total hours '
      + 'and cost, never in HPPD.'}
    roleNote="Each department's hires and orientation over the facilities shown, followed by its roles." />
}
