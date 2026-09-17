export type NetChangeFacility = {
  facility_code: string; facility_name: string; state: string; portfolio: string; region: string
  opening_census: number | null; closing_census: number | null
  admissions: number; discharges: number; net_change: number; prior_net_change: number | null
  payer_changes_in?: number; payer_changes_out?: number
  payer_changes?: number
}

export type NetChangeReport = {
  items: NetChangeFacility[]; census_available: boolean; prior_available: boolean
  prior_start_date: string; prior_end_date: string
}

export type PayerNetChangeFacility = Omit<NetChangeFacility, 'prior_net_change'> & {
  payer_type: string
  payer_changes_in: number
  payer_changes_out: number
}

export async function getPayerNetChange(startDate: string, endDate: string, signal?: AbortSignal): Promise<{ items: PayerNetChangeFacility[] }> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${base}/api/v1/adt/net-change/payers?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Payer net change could not load (status ${response.status}).`)
  }
  return response.json() as Promise<{ items: PayerNetChangeFacility[] }>
}

export async function getNetChange(startDate: string, endDate: string, signal?: AbortSignal, payerTypes: string[] = []): Promise<NetChangeReport> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
  payerTypes.forEach(payer => params.append('payer_type', payer))
  const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const response = await fetch(`${base}/api/v1/adt/net-change?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Net change could not load (status ${response.status}).`)
  }
  return response.json() as Promise<NetChangeReport>
}
