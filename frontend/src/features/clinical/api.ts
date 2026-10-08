import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

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

export type DailyTransfers = { days: { date: string; transfers: number }[] }

/** Each day's transfers with the same filters, over the given facilities or all
 * of them when the list is empty. */
export function getDailyTransfers(startDate: string, endDate: string, payerTypes: string[], reasons: string[],
    facilityIds: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payerTypes.forEach(payer => params.append('payer_types', payer))
  reasons.forEach(reason => params.append('reasons', reason))
  facilityIds.forEach(id => params.append('facility_ids', id))
  return readJson<DailyTransfers>(`${base}/api/v1/clinical/hospital-transfers/daily?${params}`, signal)
}

// --- Logs tab --------------------------------------------------------------

export const transferLogsBase = `${base}/api/v1/clinical/hospital-transfers/logs`

export type TransferLogsQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

/** One hospital transfer. */
export type TransferLog = {
  transfer_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  admission_date: string
  transfer_date: string
  // Days from admission to the transfer.
  length_of_stay: number
  within_30_days: 'Yes' | 'No'
  admission_source: string
  rehospitalization: 'Yes' | 'No'
  payer_type: string
  payer_name: string
  reason: string
  // The hospital the resident was transferred to.
  hospital_name: string
}

function transferLogParameters(start: string, end: string, query: TransferLogsQuery, offset = 0) {
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'transfer-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getTransferLogs(start: string, end: string, offset: number, query: TransferLogsQuery,
    signal?: AbortSignal) {
  return readJson<{ items: TransferLog[]; total: number; limit: number; offset: number }>(
    `${transferLogsBase}?${transferLogParameters(start, end, query, offset)}`, signal)
}

export async function downloadTransferLogs(start: string, end: string, query: TransferLogsQuery) {
  const response = await authorizedFetch(`${transferLogsBase}/export?${transferLogParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Transfer export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `hospital-transfers-${start}-to-${end}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
