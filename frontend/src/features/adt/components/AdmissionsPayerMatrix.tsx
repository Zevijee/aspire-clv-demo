import { useEffect, useMemo, useState } from 'react'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { formatPayerType, getPayerFacilityCounts, type PayerFacilityCount } from '../api/admissions'
import type { DrilldownRow, DrilldownScope } from '../utils/admissionsDrilldown'

type PayerRow = { payer: string; counts: Map<string, number> }

export function AdmissionsPayerMatrix({ startDate, endDate, locations, scope, loading, error, onRetry }: {
  startDate: string; endDate: string; locations: DrilldownRow[]; scope: DrilldownScope
  loading: boolean; error: string | null; onRetry: () => void
}) {
  const [attempt, setAttempt] = useState(0)
  const key = useMemo(() => ({ startDate, endDate, attempt }), [startDate, endDate, attempt])
  const [result, setResult] = useState<{ key: typeof key; items?: PayerFacilityCount[]; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getPayerFacilityCounts(startDate, endDate).then(
      (items) => { if (active) setResult({ key, items }) },
      () => { if (active) setResult({ key, error: 'Payer admissions could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [startDate, endDate, key])
  const response = result?.key === key ? result : null
  const orderedLocations = [...locations].sort((a, b) => b.current - a.current || a.name.localeCompare(b.name))
  const payerRows = new Map<string, PayerRow>()
  for (const item of response?.items ?? []) {
    const location = orderedLocations.find((row) => item.state === row.state
      && (scope === null || item.portfolio === row.portfolio)
      && (scope?.portfolio === undefined || item.region === row.region)
      && (scope?.region === undefined || item.facility === row.name))
    if (!location) continue
    const row = payerRows.get(item.payer_type) ?? { payer: item.payer_type, counts: new Map<string, number>() }
    row.counts.set(location.key, (row.counts.get(location.key) ?? 0) + item.admissions)
    payerRows.set(item.payer_type, row)
  }
  const columns: TableColumn<PayerRow>[] = [
    { id: 'payer', header: 'Payer', highlightOnHover: false, isRowHeader: true, value: (row) => formatPayerType(row.payer) },
    ...orderedLocations.map((location): TableColumn<PayerRow> => ({
      id: location.key, header: location.name, numeric: true, initialSortDirection: 'descending',
      value: (row) => row.counts.get(location.key) ?? 0, format: (value) => value.toLocaleString(),
    })),
  ]
  return <Table stickyFirstColumn title="Admissions by payer" subtitle="" highlightColumnOnHover
    columns={columns} rows={[...payerRows.values()].sort((a, b) => formatPayerType(a.payer).localeCompare(formatPayerType(b.payer)))}
    getRowKey={(row) => row.payer} loading={loading || response === null} error={error ?? response?.error}
    onRetry={() => { if (error) onRetry(); setAttempt((value) => value + 1) }}
    emptyMessage="No payer admissions match this view." />
}
