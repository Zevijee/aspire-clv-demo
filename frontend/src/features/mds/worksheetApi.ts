import { readJson } from '../adt/api/admissionsOverview'
import { authorizedFetch } from '../auth/api'
import { medicareBase } from './api'

const worksheetBase = medicareBase.replace(/current-medicare$/, 'pdpm-worksheet')

/** Which date the page's range applies to: each stay's start, or its ARD. */
export type WorksheetDateBasis = 'start' | 'ard'

/** The page's date basis, from its date_basis parameter; stay start by default. */
export const worksheetDateBasis = (params: URLSearchParams): WorksheetDateBasis =>
  params.get('date_basis') === 'ard' ? 'ard' : 'start'

/** The filter-options endpoint for one date basis, so menus match the table. */
export const worksheetFilterOptions = (dateBasis: WorksheetDateBasis) =>
  `${worksheetBase}/filter-options?${new URLSearchParams({ date_basis: dateBasis })}`

// text is a group's Reply: free text, saved as the entry's note.
export type WorksheetFieldKind = 'choice' | 'score' | 'diagnoses' | 'hipps' | 'text'

/** One worksheet cell: what it is called, its group (column), what it accepts. */
export type WorksheetField = {
  id: string
  group: string
  label: string
  kind: WorksheetFieldKind
  options?: { value: string; label: string; points?: number }[]
  min?: number
  max?: number
}

export type WorksheetCatalog = { fields: WorksheetField[]; mds_due_days: number }

export type WorksheetCell = {
  value: string | null; label: string | null; note: string | null
  author: string; created_at: string; entry_id: string
}

export type WorksheetNtaItem = {
  value: string; label: string; points: number; note: string | null; author: string; entry_id: string
}

/** A HIPPS code priced over a 100-day Medicare stay at the stay's contract rate. */
export type StayRates = { average_rate: number; neutral_rate: number; total_revenue: number }

export type WorksheetRow = {
  payer_stay_id: string
  stay_id: string
  resident_name: string
  facility_name: string
  state: string
  portfolio: string
  region: string
  payer_label: string
  // First day of this Medicare payer period.
  medicare_start: string
  // Yes if this Medicare stay is still running on the latest census day.
  active: 'Yes' | 'No'
  // How it began: at admission, or by disenrolling from Medicare Advantage.
  start_reason: 'Admission' | 'Disenrollment'
  // Why an ended stay ended, and its last day; null while active.
  end_reason: 'Payer change' | 'Discharge' | null
  ended_on: string | null
  ard: string | null
  // ARD plus 14 days; null once the MDS is complete.
  due_date: string | null
  mds_status: 'Complete' | 'Due' | 'Overdue'
  // The coded PDPM code plus the 5-day assessment indicator; null until coded.
  final_hipps: string | null
  // Each HIPPS priced over a full 100-day stay, by the formula the data uses;
  // null until there is a code.
  final_rates: StayRates | null
  projected_rates: StayRates | null
  // Latest set entry per cell id.
  cells: Record<string, WorksheetCell>
  nta: { items: WorksheetNtaItem[]; points: number; band: string }
  // Entries per cell, replies included.
  activity: Record<string, number>
}

export type WorksheetPage = { items: WorksheetRow[]; total: number; census_date: string }

export type WorksheetQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: { columnId: string; direction: 'ascending' | 'descending' } | null
}

export type WorksheetEntry = {
  entry_id: string
  field: string
  action: 'set' | 'add' | 'remove' | 'reply'
  value: string | null
  label: string | null
  note: string | null
  reply_to: string | null
  author: string
  created_at: string
}

export type NewWorksheetEntry = {
  field: string
  action: WorksheetEntry['action']
  value?: string | null
  note?: string | null
  reply_to?: string | null
}

export function getWorksheetCatalog(signal?: AbortSignal) {
  return readJson<WorksheetCatalog>(`${worksheetBase}/catalog`, signal)
}

/** Medicare PDPM stays whose start (or ARD) falls from startDate to endDate, inclusive. */
export function getWorksheet(startDate: string, endDate: string, dateBasis: WorksheetDateBasis, offset: number,
    query: WorksheetQuery, signal?: AbortSignal) {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, date_basis: dateBasis,
    limit: '50', offset: String(offset),
    filters: JSON.stringify(query.filters), search: query.search?.trim() ?? '',
    sort: query.sort?.columnId ?? 'resident',
    direction: query.sort?.direction === 'descending' ? 'desc' : 'asc' })
  return readJson<WorksheetPage>(`${worksheetBase}?${params}`, signal)
}

export function getWorksheetLog(payerStayId: string, field: string, signal?: AbortSignal) {
  return readJson<WorksheetEntry[]>(
    `${worksheetBase}/${payerStayId}/entries?${new URLSearchParams({ field })}`, signal)
}

/** Append one entry to a cell's log; the API validates it and records who wrote it. */
export async function addWorksheetEntry(payerStayId: string, entry: NewWorksheetEntry) {
  const response = await authorizedFetch(`${worksheetBase}/${payerStayId}/entries`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(entry) })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(typeof body.detail === 'string' ? body.detail : `Could not save (${response.status}).`)
  }
  return await response.json() as WorksheetEntry
}
