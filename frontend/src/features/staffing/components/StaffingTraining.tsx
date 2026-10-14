import { StaffingSectionReport, type SectionMetric } from './StaffingSectionReport'

// The Staffing Overview's Training section, with what an hour of it pays.
const metrics: SectionMetric[] = [
  ['training_hours', 'Training hours', 'hours'],
  ['training_share', 'Training share', 'share'],
  ['training_rate', 'Training rate', 'rate'],
  ['training_cost', 'Training cost', 'money'],
]

/** Training: the in-service training employees take -- yearly compliance and
 * competency sessions -- and what it costs, by location and by role. */
export function StaffingTraining() {
  return <StaffingSectionReport name="Training" metrics={metrics}
    describe={(roleNames, range) => `In-service training, ${roleNames}, ${range}. Training hours are the hours employees `
      + 'spent in sessions, paid at the in-house rate; training share is their part of total hours -- hours worked, '
      + 'orientation and training -- and the training rate their pay over their hours. Training is paid time, not '
      + 'care: it is in total hours and cost, never in HPPD.'}
    roleNote="Each department's training over the facilities shown, followed by its roles." />
}
