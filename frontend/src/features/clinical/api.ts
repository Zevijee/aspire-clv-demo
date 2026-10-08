import { readJson } from '../adt/api/admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

/** One facility's hospital transfers in the range: sums, for the page to add
 * up and divide once at any drilldown level. */
export type FacilityTransfers = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  // Discharges to a hospital.
  transfers: number
  // Of those, no more than 30 days after admission.
  within_30_days: number
  // Days from admission to transfer, summed: divide by transfers.
  los_days: number
  // Admitted from a hospital and sent back within 30 days.
  rehospitalizations: number
  // Closing census summed over the range: the per-1,000 rate divides by it.
  resident_days: number
  // The same count over the same number of days just before the range, with the
  // same filters; null when those days were never generated.
  prior_transfers: number | null
  // Transfers by payer type on the day, and by clinical reason. Each applies the
  // other's filter but not its own, so it keeps every slice to click.
  payers: Record<string, number>
  reasons: Record<string, number>
}

export type HospitalTransfersReport = {
  start_date: string; end_date: string; prior_start_date: string; prior_end_date: string
  items: FacilityTransfers[]
}

/** Payer types and reasons filter the report; empty means all. */
export function getHospitalTransfers(startDate: string, endDate: string, payerTypes: string[], reasons: string[],
    signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payerTypes.forEach(payer => params.append('payer_types', payer))
  reasons.forEach(reason => params.append('reasons', reason))
  return readJson<HospitalTransfersReport>(`${base}/api/v1/clinical/hospital-transfers?${params}`, signal)
}
