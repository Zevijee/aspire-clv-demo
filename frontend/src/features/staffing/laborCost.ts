import { type FacilityOverview, type RoleOverview } from './api'

/** What an overtime and a holiday hour pay over straight time, as a share of their pay. */
export type Premiums = { overtime: number; holiday: number }

export type LaborCost = {
  /** Closing census summed over the range, once per facility, never per role. */
  censusDays: number
  /** Each measure of the chosen roles, summed over the facilities. */
  sums: Record<keyof RoleOverview, number>
  /** Classroom and floor orientation hours, and their pay. */
  orientationHours: number
  orientationCost: number
  /** Hours worked plus paid orientation and in-service training. */
  totalHours: number
  overtimePremium: number
  holidayPremium: number
  /** Straight-time pay plus the agency, overtime and holiday premiums, orientation, training and bonuses. */
  totalCost: number
  /** Every hour up to each day's budget at straight time: excess and every premium left out. */
  lowestCost: number
  /** The budgeted hours at straight time: each facility and role's target hours at its own
   * straight-time rate, summed -- never one blended rate times all the target hours. */
  budgetCost: number
}

// Each table cell asks for its row's cost, and sorting asks again: a row's
// cost is worked out once per set of roles and premiums and reused, keyed on
// the row's facility list, which every cell of the row shares. Measured: the
// Overview spent 2.3 s working the same sums out per cell.
const costs = new WeakMap<FacilityOverview[], Map<string, LaborCost>>()

/** The labour cost of some roles over some facilities, summed before anything is
 * divided, for the Staffing Overview and PPD reports alike, so the two always
 * show the same figures. */
export function laborCost(facilities: FacilityOverview[], roles: string[], premiums: Premiums): LaborCost {
  const key = `${roles.join(',')}|${premiums.overtime}|${premiums.holiday}`
  let byKey = costs.get(facilities)
  if (!byKey) costs.set(facilities, byKey = new Map())
  const known = byKey.get(key)
  if (known) return known
  const cost = computeLaborCost(facilities, roles, premiums)
  byKey.set(key, cost)
  return cost
}

function computeLaborCost(facilities: FacilityOverview[], roles: string[], premiums: Premiums): LaborCost {
  const sums = {} as Record<keyof RoleOverview, number>
  let censusDays = 0
  let budgetCost = 0
  for (const facility of facilities) {
    censusDays += facility.census_days
    for (const code of roles) {
      const role = facility.roles[code]
      if (!role) continue
      for (const [key, value] of Object.entries(role)) {
        sums[key as keyof RoleOverview] = (sums[key as keyof RoleOverview] ?? 0) + value
      }
      if (role.hours > 0) budgetCost += role.target_hours * role.wages / role.hours
    }
  }
  const n = (key: keyof RoleOverview) => sums[key] ?? 0
  const overtimePremium = n('overtime_wages') * premiums.overtime
  const holidayPremium = n('holiday_wages') * premiums.holiday
  const orientationHours = n('classroom_orientation_hours') + n('floor_orientation_hours')
  const orientationCost = n('classroom_orientation_wages') + n('floor_orientation_wages')
  return {
    censusDays, sums, budgetCost, overtimePremium, holidayPremium, orientationHours, orientationCost,
    totalHours: n('hours') + orientationHours + n('training_hours'),
    totalCost: n('wages') + n('agency_premium') + overtimePremium + holidayPremium + orientationCost
      + n('training_wages') + n('bonuses'),
    lowestCost: n('wages') - n('excess_wages'),
  }
}

export type MeasureKind = 'count' | 'average' | 'hppd' | 'variance' | 'hours' | 'signedHours' | 'rate' | 'signedRate'
  | 'money' | 'signedMoney' | 'share'

/** A staffing measure as the reports show it. */
export function formatMeasure(value: number | string, kind: MeasureKind) {
  if (typeof value !== 'number') return value
  const fixed = (digits: number) => value.toLocaleString(undefined, { minimumFractionDigits: digits,
    maximumFractionDigits: digits })
  // Rounded first, so a difference too small to show reads 0.00, never −0.00.
  const signed = (prefix: string) => {
    const shown = Math.round(value * 100) / 100
    return shown === 0 ? `${prefix}0.00` : `${shown > 0 ? '+' : '−'}${prefix}${Math.abs(shown).toFixed(2)}`
  }
  if (kind === 'average') return fixed(1)
  if (kind === 'hppd') return fixed(2)
  if (kind === 'share') return `${(value * 100).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
  if (kind === 'variance') return signed('')
  if (kind === 'rate') return `$${fixed(2)}`
  if (kind === 'signedRate') return signed('$')
  if (kind === 'money') return `$${Math.round(value).toLocaleString()}`
  if (kind === 'signedHours') {
    const shown = Math.round(value)
    return shown === 0 ? '0' : `${shown > 0 ? '+' : '−'}${Math.abs(shown).toLocaleString()}`
  }
  if (kind === 'signedMoney') {
    const shown = Math.round(value)
    return shown === 0 ? '$0' : `${shown > 0 ? '+' : '−'}$${Math.abs(shown).toLocaleString()}`
  }
  return fixed(0)
}
