import { useEffect, useState } from 'react'
import { getPayerNetChange, type PayerNetChangeFacility } from '../api/netChange'
import { DivergingBarChart } from '../../../shared/components/charts/DivergingBarChart'
import { matchesLocation } from '../utils/admissionsOverviewFilters'
import { formatPayerType } from '../api/admissions'

const metrics = ['opening_census', 'closing_census', 'admissions', 'discharges',
  'payer_changes_in', 'payer_changes_out', 'net_change'] as const
type PayerRow = { payer_type: string } & Record<typeof metrics[number], number>
const emptyRow = (payer: string): PayerRow => ({ payer_type: payer, opening_census: 0,
  closing_census: 0, admissions: 0, discharges: 0, payer_changes_in: 0,
  payer_changes_out: 0, net_change: 0 })
export function PayerNetChangeTable({ startDate, endDate, path, locations = [], selectedPayers = [], onSelectPayer, onClearPayers }: {
  startDate: string; endDate: string; path: string[]
  locations?: string[]
  selectedPayers?: string[]; onSelectPayer?: (payer: string) => void
  onClearPayers?: () => void
}) {
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, retry])
  const [response, setResponse] = useState<{ key: string; items: PayerNetChangeFacility[] } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getPayerNetChange(startDate, endDate, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key, items: data.items }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, key])
  const items = response?.key === key ? response.items : null
  const error = failure?.key === key ? failure.message : null
  const grouped = new Map<string, PayerRow>()
  for (const item of items ?? []) {
    if (!matchesLocation({ ...item, facility: item.facility_name }, locations)) continue
    const hierarchy = [item.state, item.portfolio, item.region, item.facility_name]
    if (!path.every((part, index) => hierarchy[index] === part)) continue
    const row = grouped.get(item.payer_type) ?? emptyRow(item.payer_type)
    for (const metric of metrics) row[metric] += item[metric] ?? 0
    grouped.set(item.payer_type, row)
  }
  const rows = [...grouped.values()].sort((a, b) => b.net_change - a.net_change || a.payer_type.localeCompare(b.payer_type))
  return <DivergingBarChart title="Total net change by payer"
    subtitle={`Select one or more payers to filter the table above. Click anywhere on a row.${path.length ? ` ${path.join(' / ')}` : locations.length ? ' Selected locations.' : ''}`}
    items={rows.map(row => ({ id: row.payer_type, label: formatPayerType(row.payer_type), value: row.net_change }))}
    selectedIds={selectedPayers} onSelect={onSelectPayer}
    loading={items === null && error === null} error={error}
    onRetry={() => setRetry(count => count + 1)}
    headerActions={<>
      {selectedPayers.length > 0 && onClearPayers && <button type="button"
        className="report-table__clear-filters" onClick={onClearPayers}>Clear all</button>}
    </>} />
}
