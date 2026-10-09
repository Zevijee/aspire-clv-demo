import { readJson } from '../adt/api/admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// The header Roles dropdown, kept in the URL; empty means every role.
export const ROLE_PARAM = 'ppd_role'

// shared/staffing.py ROLES, in report order; the API names the same codes.
export const STAFFING_ROLES = [
  { value: 'rn', label: 'RN', context: 'Nursing' },
  { value: 'lpn', label: 'LPN', context: 'Nursing' },
  { value: 'cna', label: 'CNA', context: 'Nursing' },
  { value: 'pt', label: 'PT', context: 'Therapy' },
  { value: 'pta', label: 'PTA', context: 'Therapy' },
  { value: 'ot', label: 'OT', context: 'Therapy' },
  { value: 'cota', label: 'COTA', context: 'Therapy' },
  { value: 'slp', label: 'SLP', context: 'Therapy' },
  { value: 'dietary_aide', label: 'Dietary Aide', context: 'Support' },
  { value: 'cook', label: 'Cook', context: 'Support' },
  { value: 'evs', label: 'EVS', context: 'Support' },
]

/** One role's sums at one facility over the range, to add up and divide once. */
export type RoleHours = {
  hours: number
  // Target PPD x each day's census, summed.
  target_hours: number
  // Hours over each day's target, summed over days.
  excess_hours: number
  short_hours: number
  // Pay for the hours worked: the average rate is wages / hours.
  wages: number
  // The excess hours at each day's rate.
  excess_wages: number
}

export type FacilityStaffing = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Closing census summed over the range: PPD divides by it.
  census_days: number
  roles: Record<string, RoleHours>
}

export type PpdReport = { start_date: string; end_date: string; items: FacilityStaffing[] }

export function getPpd(startDate: string, endDate: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return readJson<PpdReport>(`${base}/api/v1/staffing/ppd?${params}`, signal)
}
