import { useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getHistoricalComparisons, type HistoricalComparisons } from '../api/admissions'
import type { DrilldownRow, DrilldownScope } from '../utils/admissionsDrilldown'

const labels: Record<string, string> = {
  prior: 'Vs prior period', average: 'Vs all-time average',
  year: 'Vs same time last year', 'two-years': 'Vs same time two years ago',
}
type ComparisonRow = { key: string; start: string; end: string }

export function AdmissionsComparisons({ startDate, endDate, rows, scope, loading, error, onRetry }: {
  startDate: string; endDate: string; rows: DrilldownRow[]; scope: DrilldownScope
  loading: boolean; error: string | null; onRetry: () => void
}) {
  const [attempt, setAttempt] = useState(0)
  const key = useMemo(() => ({ startDate, endDate, attempt }), [startDate, endDate, attempt])
  const [result, setResult] = useState<{ key: typeof key; data?: HistoricalComparisons; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getHistoricalComparisons(startDate, endDate).then(
      (data) => { if (active) setResult({ key, data }) },
      () => { if (active) setResult({ key, error: 'Historical comparisons could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [startDate, endDate, key])
  const response = result?.key === key ? result : null
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const columns: TableColumn<ComparisonRow>[] = [
    { id: 'comparison', header: 'Comparison', isRowHeader: true, sortable: false,
      value: (row) => labels[row.key],
      format: (_, row) => <span title={`${row.start} to ${row.end}`}>{labels[row.key]}</span> },
    ...[...rows].sort((a, b) => b.current - a.current || a.name.localeCompare(b.name)).map((location): TableColumn<ComparisonRow> => {
      const items = response?.data?.items.filter((item) => item.state === location.state
        && (scope === null || item.portfolio === location.portfolio)
        && (scope?.portfolio === undefined || item.region === location.region)
        && (scope?.region === undefined || item.name === location.name)) ?? []
      function baseline(row: ComparisonRow) {
        if (!items.length || items.some((item) => typeof item[row.key] !== 'number')) return null
        return items.reduce((sum, item) => sum + (item[row.key] as number), 0)
      }
      return { id: location.key, header: location.name, numeric: true, sortable: false,
        change: { favorable: 'increase', value: (row) => {
          const prior = baseline(row)
          return prior === null ? null : location.current / days - prior
        } },
        value: (row) => {
          const prior = baseline(row)
          if (prior === null) return 'N/A'
          if (prior === 0) return location.current === 0 ? 0 : 'New'
          return (location.current / days - prior) / prior * 100
        },
        format: (value, row) => {
          const prior = baseline(row)
          const direction = typeof value === 'number' ? value > 0 ? 'Up' : value < 0 ? 'Down' : 'Unchanged' : value === 'New' ? 'Up from zero' : 'N/A'
          return <span 
            title={prior === null ? 'This comparison period is outside available history.' : `${(location.current / days).toFixed(2)} current vs ${prior.toFixed(2)} baseline admissions/day (${row.start} to ${row.end})`}>
            {direction}{typeof value === 'number' && value !== 0 ? ` ${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}%` : ''}
          </span>
        },
      }
    }),
  ]
  return <Table highlightColumnOnHover title="Admissions comparisons"
    subtitle="Change in average daily admissions. All-time uses all available history. Hover for comparison dates and daily averages."
    columns={columns} rows={response?.data?.periods ?? []} getRowKey={(row) => row.key}
    loading={loading || response === null} error={error ?? response?.error}
    onRetry={() => { setAttempt((value) => value + 1); if (error) onRetry() }}
    emptyMessage="No comparison data is available." />
}
