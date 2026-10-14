import { overviewSection } from './StaffingOverview'
import { StaffingSectionReport } from './StaffingSectionReport'

// Four sections of the Staffing Overview, each as a report of its own: the
// section's columns exactly as the Overview shows them, by location and by role.

/** Hours: every kind of hour, and the total paid. */
export function StaffingHours() {
  return <StaffingSectionReport name="Hours" metrics={overviewSection('Hours')}
    describe={(roleNames, range) => `Hours by kind, ${roleNames}, ${range}. Regular, overtime and holiday hours `
      + `make up the hours worked, the hours HPPD counts: overtime is hours over 40 a week per employee, and holiday `
      + `hours the rest of the hours worked on paid holidays. Agency hours are the hours worked by agency employees, part `
      + `of the others, for reference. In-service training and classroom and floor orientation are paid on top of the `
      + `hours worked and are not in HPPD; total hours are the hours worked plus them. After each kind's hours is its share `
      + `of total hours; without agency, which is part of the others, they add up to 100%.`}
    roleNote={`Each department's hours over the facilities shown, followed by its roles.`} />
}

/** Cost: what each kind of hour cost, and the total. */
export function StaffingCost() {
  return <StaffingSectionReport name="Cost" metrics={overviewSection('Cost')}
    describe={(roleNames, range) => `What each kind of hour cost, ${roleNames}, ${range}. Regular pay is straight `
      + `time; overtime and holiday pay include their premium over straight time. Agency pay is what agency employees `
      + `were paid, part of the others, for reference. Training and orientation pay are their hours at the in-house `
      + `rate, and bonuses the sign-on bonuses paid. Total cost is straight-time pay plus the agency, overtime and `
      + `holiday premiums, orientation, training and bonuses. After each kind of pay is its share of total cost; `
      + `agency pay is part of the others, for reference.`}
    roleNote={`Each department's cost over the facilities shown, followed by its roles.`} />
}

/** Hourly rate: what an hour of each kind paid. */
export function StaffingHourlyRate() {
  return <StaffingSectionReport name="Hourly rate" metrics={overviewSection('Hourly rate')}
    describe={(roleNames, range) => `What an hour of each kind paid, ${roleNames}, ${range}: each kind's pay over `
      + `its hours, summed then divided. The average hourly rate is total cost over total hours.`}
    roleNote={`Each department's rates over the facilities shown, followed by its roles.`} />
}

/** Premiums and extras: the excess spend over budget and the agency and overtime premiums. */
export function StaffingPremiums() {
  return <StaffingSectionReport name="Premiums and extras" metrics={overviewSection('Premiums and extras')}
    describe={(roleNames, range) => `What was paid over budget and over straight time, ${roleNames}, ${range}. `
      + `Overbudget excess spend is the hours over each day's budget at straight time; the agency premium what agency `
      + `hours cost over the in-house rate; and the overtime premium what overtime hours paid over straight time. `
      + `Total premiums adds them up.`}
    roleNote={`Each department's premiums and extras over the facilities shown, followed by its roles.`} />
}
