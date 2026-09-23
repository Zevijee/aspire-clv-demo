import { payerCode, readJson, type References } from './admissionsOverview'

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

/** The monthly report's three views read three different tables, on purpose.
 *
 * Net change reads `monthly_payer_census_facts`, which carries the
 * opening/flow/closing identity. Admissions and discharges read
 * `monthly_admission_facts` and `monthly_discharge_facts`, which exist because
 * that census table has no referral source or destination and cannot gain one:
 * census is a level rather than a flow, so a resident's presence in a bed does
 * not divide by where they arrived from. All three agree on the totals they
 * share -- verified across every month.
 */
export const monthlyTabs = {
  admissions: { path: `${base}/api/v1/adt/admissions/monthly`, metric: 'admissions' },
  discharges: { path: `${base}/api/v1/adt/discharges/monthly`, metric: 'discharges' },
  'net-change': { path: `${base}/api/v1/adt/net-change/monthly`, metric: 'value' },
} as const

export type MonthlyTab = keyof typeof monthlyTabs

export const SOURCE_TYPES = ['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility',
  'Assisted Living', 'Community'] as const
export const DESTINATION_TYPES = ['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility',
  'Assisted Living', 'Community', 'Funeral Home'] as const

/** Which URL parameter narrows each view, and the label its control carries. */
export const monthlyFilter = {
  admissions: { param: 'source_types', search: 'monthly_source', label: 'Coming from',
    placeholder: 'All sources', options: SOURCE_TYPES },
  discharges: { param: 'destination_types', search: 'monthly_destination', label: 'Going to',
    placeholder: 'All destinations', options: DESTINATION_TYPES },
} as const

export function monthlyParameters({ references, payers, path, filter, values }: {
  references: References
  payers: string[]
  path: string[]
  filter?: { param: string }
  values?: string[]
}) {
  const params = new URLSearchParams()
  if (path.length) {
    // The drill-down carries location names; resolve them to saved facility ids.
    const selected = references.locations.filter(row =>
      [row.state, row.portfolio_name, row.region_name, row.facility_name]
        .every((part, index) => index >= path.length || part === path[index]))
    if (!selected.length) params.set('match_none', 'true')
    selected.forEach(row => params.append('facility_ids', row.facility_id))
  }
  payers.forEach(value => params.append('payer_types', payerCode(value)))
  if (filter) (values ?? []).forEach(value => params.append(filter.param, value))
  return params
}

export type MonthlyDay = {
  date: string
  value: number
  admissions: number
  discharges: number
  opening_census: number
  closing_census: number
  payer_changes_in: number
  payer_changes_out: number
}

export type MonthlyRow = MonthlyDay & { month: string; end_date: string; days: MonthlyDay[] }

const ZERO = {
  value: 0, admissions: 0, discharges: 0, opening_census: 0, closing_census: 0,
  payer_changes_in: 0, payer_changes_out: 0,
}

/** Fill the metrics a view does not carry.
 *
 * The admissions and discharges tables hold flows only, so they answer with one
 * measure. The table and chart read a single metric per tab, so the rest are
 * zeroed rather than faked into looking meaningful.
 */
function normalise(row: Record<string, unknown>): MonthlyRow {
  const days = (row.days as Record<string, unknown>[] | undefined) ?? []
  return {
    ...ZERO, ...row,
    days: days.map(day => ({ ...ZERO, ...day })),
  } as MonthlyRow
}

export async function getMonthlyTrend(tab: MonthlyTab, start: string, end: string,
    parameters: string, signal?: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start)
  params.set('end_date', end)
  const data = await readJson<{ months: Record<string, unknown>[] }>(
    `${monthlyTabs[tab].path}?${params}`, signal)
  return data.months.map(normalise)
}

export type MonthlyLocation = {
  facility_id: string; facility_name: string; state: string; portfolio: string; region: string
}
export type MonthlyLocationItem = { facility_id: string; month: string } & Record<string, number>

export function monthlyLocationsUrl(tab: MonthlyTab) {
  return `${monthlyTabs[tab].path}-locations`
}

export function getMonthlyLocations(tab: MonthlyTab, start: string, end: string,
    parameters: string, signal?: AbortSignal) {
  const params = new URLSearchParams(parameters)
  params.set('start_date', start)
  params.set('end_date', end)
  return readJson<{ locations: MonthlyLocation[]; items: MonthlyLocationItem[] }>(
    `${monthlyLocationsUrl(tab)}?${params}`, signal)
}
