import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import type { TableColumn } from '../../../shared/components/Table'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'

type Metric = 'admissions' | 'discharges' | 'net_change'
type Location = { facility_code: string; facility_name: string; state: string; portfolio: string; region: string }
type Result = { locations: Location[]; items: ({ facility_code: string; month: string } & Record<Metric, number>)[] }
type Row = { key: string; name: string; months: number[]; isTotal?: boolean }
const levels = ['state', 'portfolio', 'region', 'facility_name'] as const
const labels = ['State', 'Portfolio', 'Region', 'Facility']

export function MonthlyAdtLocations({ activeTab, startDate, endDate, path, setPath }: {
  activeTab: string; startDate: string; endDate: string
  path: string[]; setPath: (path: string[]) => void
}) {
  const [params] = useSearchParams()
  const [retry, setRetry] = useState(0)
  const request = new URLSearchParams({ start_date: startDate, end_date: endDate })
  params.getAll('monthly_payer').forEach(payer => request.append('payer_type', payer))
  const query = request.toString()
  const key = JSON.stringify([query, retry])
  const [response, setResponse] = useState<{ key: string; data?: Result; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/adt/net-change/monthly-locations?${query}`, { signal: controller.signal })
      .then(async result => {
        const body = await result.json()
        if (!result.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Monthly locations could not load.')
        return body as Result
      }).then(data => { if (!controller.signal.aborted) setResponse({ key, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setResponse({ key, error: error.message }) })
    return () => controller.abort()
  }, [query, key])
  const result = response?.key === key ? response : null
  const metric: Metric = activeTab === 'net-change' ? 'net_change' : activeTab === 'discharges' ? 'discharges' : 'admissions'
  const label = metric === 'net_change' ? 'Net change' : metric === 'admissions' ? 'Admissions' : 'Discharges'
  const months: string[] = []
  for (let month = dayjs(startDate).startOf('month'); !month.isAfter(dayjs(endDate), 'month'); month = month.add(1, 'month')) {
    months.push(month.format('YYYY-MM'))
  }
  const groups = new Map<string, Row>()
  const facilityGroups = new Map<string, Row>()
  const depth = Math.min(path.length, 3)
  for (const location of result?.data?.locations ?? []) {
    if (!path.every((part, index) => location[levels[index]] === part)) continue
    const name = location[levels[depth]]
    let row = groups.get(name)
    if (!row) { row = { key: name, name, months: months.map(() => 0) }; groups.set(name, row) }
    facilityGroups.set(location.facility_code, row)
  }
  for (const item of result?.data?.items ?? []) {
    const row = facilityGroups.get(item.facility_code)
    const index = months.indexOf(item.month)
    if (row && index >= 0) row.months[index] += Number(item[metric])
  }
  const extreme = (row: Row, high: boolean) => (high ? Math.max : Math.min)(...row.months)
  const change = metric === 'net_change' ? { favorable: 'increase' as const } : undefined
  const formatValue = (value: number) => value.toLocaleString(undefined, {
    maximumFractionDigits: 1, signDisplay: metric === 'net_change' ? 'exceptZero' : 'auto',
  })
  const extremeLabel = (row: Row, high: boolean) => {
    const value = extreme(row, high)
    const matches = row.months.flatMap((count, index) => count === value ? [dayjs(`${months[index]}-01`).format('MMM YYYY')] : [])
    return <span title={matches.join(', ')}>{formatValue(value)} <small>({matches[0]}{matches.length > 1 ? ` +${matches.length - 1}` : ''})</small></span>
  }
  const columns: TableColumn<Row>[] = [
    { id: 'location', header: labels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name : <button type="button" className="drilldown-table__link"
        onClick={() => setPath([...path, row.name])}>{row.name}</button> },
    { id: 'average', header: 'Average/month', numeric: true, change,
      value: row => row.months.reduce((sum, value) => sum + value, 0) / months.length,
      format: value => formatValue(Number(value)) },
    { id: 'highest', header: 'Highest month', numeric: true, change, value: row => extreme(row, true), format: (_, row) => extremeLabel(row, true) },
    { id: 'lowest', header: 'Lowest month', numeric: true, change, value: row => extreme(row, false), format: (_, row) => extremeLabel(row, false) },
  ]
  return <>
    <DrilldownNavigation items={[
      { id: 'root', label: 'All states', onSelect: () => setPath([]) },
      ...path.map((name, index) => ({ id: String(index), label: name, onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} level={{ current: depth + 1, total: 4, label: labels[depth] }} />
    <DrilldownTable title={`${label} by location`} subtitle="Monthly averages and highest and lowest months."
      columns={columns} rows={[...groups.values()]} getRowKey={row => row.key}
      getFooterRow={rows => ({ key: 'total', name: 'Total', isTotal: true,
        months: months.map((_, index) => rows.reduce((sum, row) => sum + row.months[index], 0)),
      })}
      initialSort={{ columnId: 'average', direction: 'descending' }} stickyFirstColumn
      loading={result === null} error={result?.error} onRetry={() => setRetry(value => value + 1)}
      emptyMessage="No locations match the selected range and payers."
      csvFileName={`monthly-${activeTab}-locations-${startDate}-to-${endDate}.csv`} />
  </>
}
