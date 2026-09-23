import { payerCode, readJson } from './admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
export const referringHospitalBase = `${base}/api/v1/adt/referring-hospital`

// The report's own windows, mirrored from the service so the table headings and
// the numbers they label can never describe different periods.
export const RECENT_MONTHS = 3
export const BASELINE_MONTHS = 24
export const COMPARED_MONTHS = RECENT_MONTHS + BASELINE_MONTHS

export type ReceivingFacility = {
  facility_id: string
  facility: string
  // Admissions across the compared window, not all 36 months.
  admissions: number
  // Aligned with the response `months`. Empty unless one hospital was requested.
  months: number[]
}

export type HospitalPerformance = {
  hospital: string
  state: string
  portfolio: string
  region: string
  months: number[]
  receiving_facilities: ReceivingFacility[]
  recent_average: number
  usual_average: number
  difference: number
  difference_percent: number | null
  previous_average: number
  change_percent: number | null
  six_month_average: number
  year_average: number
  historical_average: number
  change_vs_average: number
  previous_month_admissions: number
}

export type ReferringHospitalPerformance = {
  months: string[]
  start_date: string
  end_date: string
  items: HospitalPerformance[]
  data_status: {
    complete: boolean; available_from: string | null
    available_through: string | null; generated_at: string | null
  }
}

export function referringHospitalParameters(payers: string[], hospital?: string | null) {
  const params = new URLSearchParams()
  payers.map(payerCode).forEach(value => params.append('payer_types', value))
  if (hospital) params.set('hospital', hospital)
  return params
}

export function getReferringHospitalPerformance(payers: string[], hospital: string | null,
    signal?: AbortSignal) {
  return readJson<ReferringHospitalPerformance>(
    `${referringHospitalBase}/performance?${referringHospitalParameters(payers, hospital)}`, signal)
}

/** Recent versus usual for one month series, matching the service's comparison. */
export function compareMonths(months: number[]) {
  const recent = months.slice(-RECENT_MONTHS)
    .reduce((total, value) => total + value, 0) / RECENT_MONTHS
  const usual = months.slice(-COMPARED_MONTHS, -RECENT_MONTHS)
    .reduce((total, value) => total + value, 0) / BASELINE_MONTHS
  return { recent_average: recent, usual_average: usual, difference: recent - usual,
    difference_percent: usual ? (recent - usual) / usual * 100 : null }
}
