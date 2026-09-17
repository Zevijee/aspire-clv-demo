import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getPayerChangeOverview, getPayerTransitions, payerTypes, type PayerChangeOverview } from '../api/payerChanges'
import { getPayerChangeRows, getPayerChangeTotal, payerChangeLogsParams, type PayerChangeRow } from '../utils/payerChangesDrilldown'

const levels = ['State', 'Portfolio', 'Region', 'Facility']

function PayerTransitionDonut({ startDate, endDate, path, payer, onSelect }: {
  startDate: string; endDate: string; path: string[]; payer: string; onSelect: (payer: string) => void
}) {
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, path, payer, retry])
  const [response, setResponse] = useState<{
    key: string; items: { label: string; value: number }[]; error: string | null
  } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getPayerTransitions(startDate, endDate, path, payer, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setResponse({ key, items, error: null })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setResponse({ key, items: [], error: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, path, payer, key])
  const result = response?.key === key ? response : null
  return <DonutChart title={`Changed from ${payer} to…`}
    titleContent={<>Changed from <strong>{payer}</strong> to…</>}
    valueLabel="Payer changes" centerMode="total"
    subtitle={`${path.at(-1) ?? 'All states'} · Select a destination to view logs`}
    onSelect={onSelect} items={result?.items ?? []} loading={result === null}
    error={result?.error} onRetry={() => setRetry((count) => count + 1)} />
}

export function PayerChangesOverview() {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const pathKey = JSON.stringify(params.getAll('payer_scope').slice(0, 4))
  const path = useMemo(() => JSON.parse(pathKey) as string[], [pathKey])
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, retry])
  const [response, setResponse] = useState<{ key: string; data: PayerChangeOverview } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getPayerChangeOverview(startDate, endDate, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, key])
  const result = response?.key === key ? response.data : null
  const error = failure?.key === key ? failure.message : null
  const level = levels[Math.min(path.length, 3)]
  function setPath(nextPath: string[]) {
    const next = new URLSearchParams(params)
    next.delete('payer_scope')
    nextPath.forEach((part) => next.append('payer_scope', part))
    setParams(next)
  }
  const columns: TableColumn<PayerChangeRow>[] = [
    { id: 'name', header: level, isRowHeader: true, value: (row) => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button className="drilldown-table__link" type="button" onClick={() => setPath(row.path)}>
          {row.name}
        </button> },
    { id: 'total', header: 'Payer-type changes', numeric: true, value: (row) => row.total,
      format: (_, row) => row.total === 0 ? '0' :
        <button className="drilldown-table__link" type="button"
          aria-label={`View ${row.name} payer change logs`}
          onClick={() => setParams(payerChangeLogsParams(params, { facility_name: row.facilityNames }))}>
          {row.total.toLocaleString()}
        </button> },
    { id: 'residents', header: 'Residents affected', numeric: true, value: (row) => row.residents,
      format: (value) => Number(value).toLocaleString() },
    { id: 'prior', header: 'Prior-period changes', numeric: true, value: (row) => row.prior,
      format: (value) => Number(value).toLocaleString() },
    { id: 'change', header: 'Change vs prior', numeric: true, value: (row) => row.change,
      change: { favorable: 'neutral' } },
  ]
  return <>
    <DrilldownNavigation ariaLabel="Payer changes drill-down" items={[
      { id: 'all', label: 'All states', onSelect: () => setPath([]) },
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} />
    <Table key={pathKey} title={`${level} payer changes`}
      subtitle="Payer-type changes by effective date; residents counted once per facility. Compared with the preceding period of equal length. Plan-only changes are available in Logs."
      columns={columns} rows={getPayerChangeRows(result?.items ?? [], path)} getRowKey={(row) => row.key}
      initialSort={{ columnId: 'total', direction: 'descending' }} getFooterRow={getPayerChangeTotal}
      loading={result === null && error === null} error={error} onRetry={() => setRetry((count) => count + 1)}
      csvFileName={`payer-changes-${level.toLowerCase()}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No facilities match this location." />
    <div className="report-chart-grid report-chart-grid--three-columns">
      {payerTypes.map((payer) => <PayerTransitionDonut key={payer} startDate={startDate} endDate={endDate}
        path={path} payer={payer} onSelect={(destination) => {
          const selections: Record<string, string[]> = {
            previous_payer_type: [payer], new_payer_type: [destination],
          }
          path.forEach((value, index) => { selections[['state', 'portfolio', 'region', 'facility_name'][index]] = [value] })
          setParams(payerChangeLogsParams(params, selections))
        }} />)}
    </div>
  </>
}
