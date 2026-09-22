import { DivergingBarChart } from '../../../shared/components/charts/DivergingBarChart'
import { payerLabel } from '../api/admissionsOverview'
import type { NetChangePayer } from '../api/netChangeOverview'

export function PayerNetChangeTable({ rows, scopeName, selectedPayers = [],
    onSelectPayer, onClearPayers, loading, error, onRetry }: {
  rows: NetChangePayer[]
  scopeName?: string
  selectedPayers?: string[]
  onSelectPayer?: (payer: string) => void
  onClearPayers?: () => void
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}) {
  const sorted = [...rows].sort((left, right) =>
    right.net_change - left.net_change || left.payer_type.localeCompare(right.payer_type))
  return <DivergingBarChart title="Total net change by payer"
    subtitle={`Select one or more payers to filter the table above. Click anywhere on a row.${scopeName ? ` ${scopeName}` : ''}`}
    items={sorted.map(row => ({ id: row.payer_type, label: payerLabel(row.payer_type), value: row.net_change }))}
    selectedIds={selectedPayers} onSelect={onSelectPayer}
    loading={loading} error={error} onRetry={onRetry}
    headerActions={selectedPayers.length > 0 && onClearPayers
      ? <button type="button" className="report-table__clear-filters"
          onClick={onClearPayers}>Clear all</button>
      : undefined} />
}
