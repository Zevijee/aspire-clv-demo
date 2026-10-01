import { useEffect, useState } from 'react'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import type { TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { getCurrentMedicare, type CurrentMedicareReport, type FacilityMedicare } from '../api'

type Row = { key: string; name: string; path: string[]; facilities: FacilityMedicare[]; isTotal?: boolean }
type Summed = 'federal' | 'managed' | 'actual_rates' | 'neutral_rates' | 'resident_days'
const levels = ['State', 'Portfolio', 'Region', 'Facility']
function location(row: FacilityMedicare) { return [row.state, row.portfolio, row.region, row.facility_name] }

function sum(row: Row, field: Summed) {
  return row.facilities.reduce((total, facility) => total + facility[field], 0)
}
// Sums at this scope divided once by its residents: never an average of
// facility averages.
function metric(row: Row, field: string): number | null {
  const residents = sum(row, 'federal') + sum(row, 'managed')
  if (field === 'residents') return residents
  if (field === 'neutral_rate') return residents > 0 ? sum(row, 'neutral_rates') / residents : null
  if (field === 'actual_rate') return residents > 0 ? sum(row, 'actual_rates') / residents : null
  if (field === 'los') return residents > 0 ? sum(row, 'resident_days') / residents : null
  return sum(row, field as Summed)
}

const metrics: [id: string, header: string, kind: 'count' | 'rate' | 'days'][] = [
  ['residents', 'PDPM residents', 'count'], ['federal', 'Federal Medicare', 'count'],
  ['managed', 'Managed Medicare PDPM', 'count'],
  ['neutral_rate', 'Neutral rate', 'rate'], ['actual_rate', 'Actual rate', 'rate'],
  ['los', 'Avg. length of stay', 'days'],
]
function formatMetric(value: number | string, kind: 'count' | 'rate' | 'days') {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  const digits = kind === 'days' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function CurrentMedicare() {
  const [data, setData] = useState<CurrentMedicareReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [path, setPath] = useState<string[]>([])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getCurrentMedicare(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])

  const depth = Math.min(path.length, 3)
  const groups = new Map<string, Row>()
  for (const facility of data?.items ?? []) {
    const parts = location(facility)
    if (!path.every((value, index) => parts[index] === value)) continue
    const nextPath = parts.slice(0, depth + 1)
    const key = JSON.stringify(nextPath)
    const row = groups.get(key) ?? { key, name: parts[depth], path: nextPath, facilities: [] }
    row.facilities.push(facility)
    groups.set(key, row)
  }
  const nameColumn: TableColumn<Row> = { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
  const columns: TableColumn<Row>[] = [
    nameColumn,
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—', format: value => formatMetric(value, kind),
    })),
  ]
  const facilityRows: Row[] = (data?.items ?? []).map(facility => ({
    key: facility.facility_id, name: facility.facility_name, path: location(facility), facilities: [facility] }))
  const subtitle = data ? `Residents paid from their PDPM code on ${data.census_date}: Original Medicare, `
    + 'and Managed Medicare PDPM. Managed Medicare PPO pays per diem and is not included. '
    + "Neutral rate is not adjusted for the facility's case mix. Actual rate is what the payer pays." : ''

  return <>
    <DrilldownNavigation locationView={{
      groupBy: 'state', selectedCount: 0,
      onReturn: () => setPath([]),
      onClear: () => setPath([]),
    }} items={path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
      onSelect: () => setPath(path.slice(0, index + 1)) }))}
      level={{ current: depth + 1, total: 4, label: levels[depth] }} />
    <DrilldownTable<Row> title={`${levels[depth]} PDPM residents`} columns={columns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicare-${data?.census_date ?? 'today'}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      title={data ? `All facilities · PDPM residents on ${data.census_date}` : 'All facilities'} subtitle={subtitle}
      rows={facilityRows} columns={columns.slice(1)} getRowKey={row => row.key} getName={row => row.name}
      getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      csvFileName={`current-medicare-facilities-${data?.census_date ?? 'today'}.csv`} />
  </>
}
