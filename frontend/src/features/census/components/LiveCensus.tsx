import { useEffect, useState } from 'react'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import type { TableColumn } from '../../../shared/components/Table'

type Facility = {
  facility_code: string; facility_name: string; state: string; portfolio: string; region: string
  census: number | null; capacity: number; bed_holds: number | null; previous_average: number | null
}
type Report = { as_of: string; available_through: string; previous_month: string; items: Facility[] }
type Row = { key: string; name: string; path: string[]; facilities: Facility[]; isTotal?: boolean }
const levels = ['State', 'Portfolio', 'Region', 'Facility']
function location(row: Facility) { return [row.state, row.portfolio, row.region, row.facility_name] }
function sum(row: Row, field: 'census' | 'capacity' | 'bed_holds' | 'previous_average'): number | null {
  if (row.facilities.some(facility => facility[field] === null)) return null
  return row.facilities.reduce((total, facility) => total + (facility[field] ?? 0), 0)
}
function metric(row: Row, field: string): number | null {
  const census = sum(row, 'census')
  const capacity = sum(row, 'capacity') ?? 0
  const holds = sum(row, 'bed_holds')
  const average = sum(row, 'previous_average')
  if (field === 'occupancy') return census !== null && capacity > 0 ? census / capacity * 100 : null
  if (field === 'empty') return census !== null && holds !== null ? capacity - census - holds : null
  if (field === 'variance') return census !== null && average !== null ? census - average : null
  return sum(row, field as 'census' | 'capacity' | 'bed_holds' | 'previous_average')
}

export function LiveCensus() {
  const [data, setData] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [path, setPath] = useState<string[]>([])
  useEffect(() => {
    const timer = window.setInterval(() => setRetry(value => value + 1), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/census/live`, { signal: controller.signal }).then(async response => {
      const body = await response.json()
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Live census could not load.')
      if (!controller.signal.aborted) setData(body as Report)
    }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
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
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    ...[
      ['census', 'Census'], ['occupancy', 'Occupancy'], ['capacity', 'Capacity'],
      ['empty', 'Empty beds'], ['bed_holds', 'Bed holds'],
      ['previous_average', 'Prev. month avg. census'], ['variance', 'Variance'],
    ].map(([id, header]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '?',
      format: value => typeof value !== 'number' ? value : value.toLocaleString(undefined, {
        maximumFractionDigits: ['occupancy', 'previous_average', 'variance'].includes(id) ? 1 : 0,
        ...(id === 'variance' ? { signDisplay: 'exceptZero' as const } : {}),
      }) + (id === 'occupancy' ? '%' : ''),
      ...(id === 'variance' ? { change: { favorable: 'increase' as const } } : {}),
    })),
  ]
  return <>
    <DrilldownNavigation locationView={{
      groupBy: 'state', selectedCount: 0,
      onReturn: () => setPath([]),
      onClear: () => setPath([]),
    }} items={[
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} level={{ current: depth + 1, total: 4, label: levels[depth] }} />
    <DrilldownTable<Row> title={`${levels[depth]} census`} columns={columns} rows={[...groups.values()]}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={!data && !error} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={rows => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: rows.flatMap(row => row.facilities) })}
      subtitle={data ? `Today: ${data.as_of}. Previous month: ${data.previous_month.slice(0, 7)}. Variance = today's census minus previous-month average. Empty beds exclude bed holds.${data.available_through < data.as_of ? ` Census data is only available through ${data.available_through}; today's counts are unavailable.` : ''}` : ''}
      emptyMessage="No facilities match this view."
      csvFileName={`live-census-${data?.as_of ?? 'today'}.csv`} />
  </>
}
