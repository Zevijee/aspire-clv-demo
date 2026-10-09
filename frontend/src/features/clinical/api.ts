import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'

// The transfer reasons, in shared/database/schema.py TRANSFER_REASONS order; the
// API validates them against that list.
export const TRANSFER_REASONS = ['Respiratory', 'Cardiac', 'Infection or sepsis', 'Urinary tract infection',
  'Fall or injury', 'Change in mental status', 'Gastrointestinal', 'Dehydration or electrolytes',
  'Surgical complication', 'Planned procedure', 'Other']

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

// --- Incidents -------------------------------------------------------------

/** One facility's incidents in the range: sums, to add up and divide once. */
export type FacilityIncidents = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  incidents: number
  // Incidents that sent the resident to a hospital: the hospital transfers for a fall or injury.
  hospitalized: number
  // The range's incidents not closed by the latest simulated day.
  still_open: number
  // Closing census summed over the range: the per-1,000 rate divides by it.
  resident_days: number
  // By the hour each happened: 6-11, 12-17, 18-21, and 22-5.
  morning: number
  afternoon: number
  evening: number
  night: number
  // Incidents by type, and by severity level ('1' to '5'). Each applies the
  // other filters but not its own, so it keeps every slice to click.
  types: Record<string, number>
  severities: Record<string, number>
}

export type IncidentsReport = { start_date: string; end_date: string; as_of: string; items: FacilityIncidents[] }

// The incident types, in shared/database/schema.py INCIDENT_TYPES order; the API
// validates them against that list.
export const INCIDENT_TYPES = ['Fall', 'Skin tear or bruise', 'Medication error', 'Resident altercation',
  'Pressure injury', 'Elopement or wandering', 'Choking', 'Other']

// Severity by its stored level, 1 to 5, shown by name alone; major and severe
// are the major incidents.
export const SEVERITY_LEVELS: Record<string, string> = {
  1: 'No injury', 2: 'Minor', 3: 'Moderate', 4: 'Major', 5: 'Severe',
}

/** Payer types, incident types and severity levels filter the report; empty means all. */
export function getIncidents(startDate: string, endDate: string, payerTypes: string[], incidentTypes: string[],
    severities: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payerTypes.forEach(payer => params.append('payer_types', payer))
  incidentTypes.forEach(kind => params.append('incident_types', kind))
  severities.forEach(level => params.append('severities', level))
  return readJson<IncidentsReport>(`${base}/api/v1/clinical/incidents?${params}`, signal)
}

export type DailyIncidents = { days: { date: string; incidents: number }[] }

/** Each day's incidents with the same filters, over the given facilities or all
 * of them when the list is empty. */
export function getDailyIncidents(startDate: string, endDate: string, payerTypes: string[], incidentTypes: string[],
    severities: string[], facilityIds: string[], signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payerTypes.forEach(payer => params.append('payer_types', payer))
  incidentTypes.forEach(kind => params.append('incident_types', kind))
  severities.forEach(level => params.append('severities', level))
  facilityIds.forEach(id => params.append('facility_ids', id))
  return readJson<DailyIncidents>(`${base}/api/v1/clinical/incidents/daily?${params}`, signal)
}

// --- Incidents' Logs tab ---------------------------------------------------

export const incidentLogsBase = `${base}/api/v1/clinical/incidents/logs`

export type IncidentLogsQuery = TransferLogsQuery

/** One incident. */
export type IncidentLog = {
  incident_id: string
  facility_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  incident_date: string
  // 0-23, and its part of the day.
  hour: number
  time_of_day: string
  incident_type: string
  severity: string
  hospitalized: 'Yes' | 'No'
  still_open: 'Yes' | 'No'
  closed_date: string
  payer_type: string
  payer_name: string
}

function incidentLogParameters(start: string, end: string, query: IncidentLogsQuery, offset = 0) {
  return new URLSearchParams({ start_date: start, end_date: end, limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'incident-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getIncidentLogs(start: string, end: string, offset: number, query: IncidentLogsQuery,
    signal?: AbortSignal) {
  return readJson<{ items: IncidentLog[]; total: number; limit: number; offset: number }>(
    `${incidentLogsBase}?${incidentLogParameters(start, end, query, offset)}`, signal)
}

export async function downloadIncidentLogs(start: string, end: string, query: IncidentLogsQuery) {
  const response = await authorizedFetch(`${incidentLogsBase}/export?${incidentLogParameters(start, end, query)}`)
  if (!response.ok) throw new Error('Incident export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `incidents-${start}-to-${end}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- Fever / Infections ----------------------------------------------------

/** One facility and contagious type whose new cases reach watch or outbreak. */
export type InfectionAlert = {
  facility_id: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  infection_type: string
  status: 'outbreak' | 'watch'
  // New cases with onset in the 72 hours, and the 7 days, ending on the day.
  cases_72_hours: number
  cases_7_days: number
  with_fever: number
  // Not yet resolved on the day, whenever they began.
  active: number
  first_onset: string
  latest_onset: string
  wings: string[]
}

export type InfectionsBoard = {
  date: string
  // The latest generated day.
  latest: string
  facilities: number
  facilities_in_outbreak: number
  // With a watch and no outbreak.
  facilities_on_watch: number
  new_cases_72_hours: number
  active_cases: number
  // Outbreaks first, then watches.
  alerts: InfectionAlert[]
}

/** The alert board as of a day; null means the latest generated day. */
export function getInfectionsBoard(day: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams(day ? { date: day } : {})
  return readJson<InfectionsBoard>(`${base}/api/v1/clinical/fever-infections?${params}`, signal)
}

// --- Weight Surveillance ---------------------------------------------------

export const weightsBase = `${base}/api/v1/clinical/weight-surveillance`

export type WeightsQuery = TransferLogsQuery

/** One resident in a bed on the day, with this stay's weights in pounds. */
export type ResidentWeight = {
  stay_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  admission_date: string
  days_in_facility: number
  admission_weight: number
  // The latest weigh-in on or before the day, and when it was taken.
  current_weight: number
  weighed_on: string
  // Current less admission.
  change: number
  change_percent: number
  highest: number
  lowest: number
  // Highest less lowest, and that as a percent of the highest.
  weight_range: number
  range_percent: number
  // Percent, against the latest weight at least 30 and 180 days older; null
  // when the stay is younger.
  change_30_days: number | null
  change_180_days: number | null
  flag: 'Significant loss' | 'Significant gain' | 'None'
}

export type WeightsPage = {
  items: ResidentWeight[]
  total: number
  census_date: string
  // Of the whole filtered list.
  significant_loss: number
  significant_gain: number
}

function weightParameters(query: WeightsQuery, day: string | null, offset = 0) {
  const params = new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'flag', direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
  if (day) params.set('end_date', day)
  return params
}

/** Residents in a bed on the day; null means the latest day with weights. */
export function getWeights(offset: number, query: WeightsQuery, day: string | null, signal?: AbortSignal) {
  return readJson<WeightsPage>(`${weightsBase}?${weightParameters(query, day, offset)}`, signal)
}

export async function downloadWeights(query: WeightsQuery, day: string) {
  const response = await authorizedFetch(`${weightsBase}/export?${weightParameters(query, day)}`)
  if (!response.ok) throw new Error('Weight export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `weights-${day}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- Flagged Progress Notes ------------------------------------------------

export const flaggedNotesBase = `${base}/api/v1/clinical/flagged-notes`

export type FlaggedNotesQuery = TransferLogsQuery

/** A progress note from the last 10 days with a watch word in it. */
export type FlaggedNote = {
  note_id: string
  note_date: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  resident_name: string
  note_type: string
  // The payer's label: Medicare, Medicaid and so on.
  payer_type: string
  clinician: string
  // The watch words found in the text, alphabetically.
  flag_terms: string[]
  note_text: string
}

function flaggedNoteParameters(query: FlaggedNotesQuery, offset = 0) {
  return new URLSearchParams({ limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'note-date',
    direction: query.sort?.direction === 'ascending' ? 'asc' : 'desc' })
}

export function getFlaggedNotes(offset: number, query: FlaggedNotesQuery, signal?: AbortSignal) {
  return readJson<{ items: FlaggedNote[]; total: number }>(
    `${flaggedNotesBase}?${flaggedNoteParameters(query, offset)}`, signal)
}

export async function downloadFlaggedNotes(query: FlaggedNotesQuery) {
  const response = await authorizedFetch(`${flaggedNotesBase}/export?${flaggedNoteParameters(query)}`)
  if (!response.ok) throw new Error('Note export could not complete.')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'flagged-notes.csv'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
