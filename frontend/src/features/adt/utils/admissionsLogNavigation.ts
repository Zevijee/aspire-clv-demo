import { payerLabel } from '../api/admissionsOverview'
import { getDrilldownRowScope, type DrilldownRow, type DrilldownScope } from './admissionsDrilldown'

export function getAdmissionLogsParams(
  currentParams: URLSearchParams,
  row: DrilldownRow,
  scope: DrilldownScope,
  startDate: string,
  endDate: string,
  payers: string[],
  sourceTypes: string[],
  readmissionsOnly = false,
) {
  return getScopedAdmissionLogsParams(currentParams, getDrilldownRowScope(row, scope),
    startDate, endDate, payers, sourceTypes, readmissionsOnly, row.facilityNames)
}

function getScopedAdmissionLogsParams(
  currentParams: URLSearchParams,
  scope: DrilldownScope,
  startDate: string,
  endDate: string,
  payers: string[],
  sourceTypes: string[],
  readmissionsOnly = false,
  facilities?: string[],
) {
  const params = new URLSearchParams(currentParams)
  for (const key of [...params.keys()]) {
    if (key.startsWith('logs_')) params.delete(key)
  }
  params.set('view', 'logs')
  params.set('start_date', startDate)
  params.set('end_date', endDate)
  if (readmissionsOnly) params.set('logs_readmission', 'true')
  for (const [key, value] of Object.entries(scope ?? {})) {
    if (value !== undefined) params.set(`logs_${key}`, value)
  }
  for (const payer of payers) params.append('logs_payer', payer)
  if (facilities !== undefined) {
    params.delete('logs_facility')
    for (const facility of facilities) params.append('logs_facility', facility)
  }
  for (const source of sourceTypes) params.append('logs_source-type', source)
  return params
}

export function getHospitalAdmissionLogsParams(
  currentParams: URLSearchParams, scope: DrilldownScope,
  startDate: string, endDate: string, payers: string[], hospital: string,
  facilities?: string[],
) {
  const params = getScopedAdmissionLogsParams(currentParams, scope, startDate, endDate, payers, ['Hospital'], false, facilities)
  params.set('logs_admission-source', hospital)
  return params
}

export function getAdmissionLogsFilters(params: URLSearchParams): Record<string, string[]> {
  const filters: Record<string, string[]> = {}
  if (params.get('logs_readmission') === 'true') filters.readmission = ['Yes']
  for (const key of ['state', 'portfolio', 'region', 'facility', 'facility-id', 'payer', 'source-type', 'admission-source']) {
    const values = params.getAll(`logs_${key}`)
    if (values.length) {
      filters[key] = key === 'payer'
        ? values.map(payerLabel)
        : values
    }
  }
  return filters
}
