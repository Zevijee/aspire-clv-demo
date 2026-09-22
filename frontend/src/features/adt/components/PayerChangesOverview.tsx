import { useMemo } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DataState } from '../../../shared/components/DataState'
import { DrilldownNavigation, type DrilldownBreadcrumb } from '../../../shared/components/DrilldownNavigation'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { usePayerChangesOverview } from '../hooks/usePayerChangesOverview'
import { payerLabel } from '../api/admissionsOverview'
import {
  payerChangeParameters, payerTypes,
  type PayerChangeLocation, type PayerChangeSelection,
} from '../api/payerChangesOverview'
import { payerChangeLogsParams } from '../utils/payerChangesDrilldown'
import type { DrilldownScope } from '../utils/admissionsDrilldown'

type Row = PayerChangeLocation & { prior: number | null; change: number | null; isTotal?: boolean }

export function PayerChangesOverview() {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const priorEnd = dayjs(startDate).subtract(1, 'day').format('YYYY-MM-DD')
  const priorStart = dayjs(startDate).subtract(days, 'day').format('YYYY-MM-DD')

  // Scope lives in the URL so a drill-down survives a reload and can be linked.
  const scopeKey = JSON.stringify(params.getAll('payer_scope').slice(0, 4))
  const path = useMemo(() => JSON.parse(scopeKey) as string[], [scopeKey])
  const scope: DrilldownScope = path.length
    ? { state: path[0], portfolio: path[1], region: path[2], facility: path[3] } : null
  const level = scope === null ? 'state'
    : scope.portfolio === undefined ? 'portfolio'
    : scope.region === undefined ? 'region' : 'facility'
  const detail = scope?.facility !== undefined
  const selection: PayerChangeSelection = { scope, typeChangesOnly: true }

  const references = useAdmissionsReferences()
  const parameters = references.data
    ? payerChangeParameters(selection, references.data, level).toString() : null
  const current = usePayerChangesOverview(startDate, endDate, parameters)
  const previous = usePayerChangesOverview(priorStart, priorEnd, parameters)
  const status = {
    loading: references.loading || current.loading,
    error: references.error ?? current.error,
    onRetry: references.error ? references.onRetry : current.onRetry,
  }

  const priorRows = new Map(previous.data?.locations.map(row => [row.id, row.changes]))
  const rows: Row[] = (current.data?.locations ?? []).map(row => {
    const prior = previous.data ? priorRows.get(row.id) ?? 0 : null
    return { ...row, prior, change: prior === null ? null : row.changes - prior }
  })

  function setPath(next: string[]) {
    const params2 = new URLSearchParams(params)
    params2.delete('payer_scope')
    next.forEach(part => params2.append('payer_scope', part))
    setParams(params2)
  }
  function openLogs(selections: Record<string, string[]>) {
    setParams(payerChangeLogsParams(params, selections, startDate, endDate))
  }
  const breadcrumbs: DrilldownBreadcrumb[] = [
    { id: 'all', label: 'All states', onSelect: () => setPath([]) },
    ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
      onSelect: () => setPath(path.slice(0, index + 1)) })),
  ]
  function total(visible: Row[]): Row | null {
    if (visible.length < 2) return null
    const sum = (pick: (row: Row) => number) => visible.reduce((value, row) => value + pick(row), 0)
    const changes = sum(row => row.changes)
    const prior = visible.some(row => row.prior === null) ? null : sum(row => row.prior!)
    return { id: 'total', name: 'Total', level, path: [], isTotal: true, changes,
      prior, change: prior === null ? null : changes - prior,
      average_per_day: changes / days,
      // The API's exact distinct count for the whole selection. Summing the rows
      // would double count a resident who changed payer in two locations.
      residents: current.data?.residents ?? 0,
      facility_ids: [...new Set(visible.flatMap(row => row.facility_ids))] }
  }
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: level[0].toUpperCase() + level.slice(1), isRowHeader: true, value: row => row.name,
      format: (_, row) => {
        const name = <span className="admissions-explorer__entity"><strong>{row.name}</strong></span>
        return row.isTotal || detail ? name
          : <button type="button" className="admissions-explorer__drill"
              onClick={() => setPath(row.path.map(part => part.name))}>{name}</button>
      } },
    { id: 'total', header: 'Payer-type changes', numeric: true, initialSortDirection: 'descending',
      value: row => row.changes,
      format: (value, row) => row.changes === 0 ? '0' : <button type="button"
        className="admissions-explorer__drill admissions-explorer__drill--count"
        aria-label={`View ${row.name} payer change logs`}
        onClick={() => openLogs({ 'facility-id': row.facility_ids, category: ['Payer type'] })}>
        {value.toLocaleString()}</button> },
    { id: 'residents', header: 'Residents affected', numeric: true, value: row => row.residents,
      format: value => Number(value).toLocaleString() },
    { id: 'prior', header: 'Prior-period changes', numeric: true, value: row => row.prior ?? '—',
      format: value => value.toLocaleString() },
    { id: 'change', header: 'Change vs prior', numeric: true, value: row => row.change ?? '—',
      change: { favorable: 'neutral' } },
  ]
  const transitions = current.data?.transitions ?? []
  const incoming = (payer: string) => transitions
    .filter(row => row.new_payer_type === payer)
    .reduce((total, row) => total + row.changes, 0)
  const scopeName = path.at(-1) ?? 'All states'
  return <>
    <DrilldownNavigation ariaLabel="Payer changes drill-down" items={breadcrumbs} />
    {previous.error && !status.error && <DataState label="Prior period"
      error={`Prior period: ${previous.error}`} onRetry={previous.onRetry} />}
    <Table {...status} key={scopeKey} columns={columns} rows={rows} getRowKey={row => row.id}
      getFooterRow={total} initialSort={{ columnId: 'total', direction: 'descending' }}
      title={`${level[0].toUpperCase() + level.slice(1)} payer changes`}
      subtitle="Payer-type changes by effective date; residents counted once per facility. Compared with the preceding period of equal length. Plan-only changes are available in Logs."
      csvFileName={`payer-changes-${level}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No locations match this view." />
    <div className="report-chart-grid report-chart-grid--three-columns">
      {/* Grouped by where residents landed, not where they left. Only a few
          payer types are ever a destination, so the other direction leaves most
          of these cards empty. Busiest destination first, so the empty cards
          fall to the end instead of splitting the row. */}
      {[...payerTypes]
        .sort((left, right) => incoming(right) - incoming(left) || left.localeCompare(right))
        .map(payer => {
        const into = transitions.filter(row => row.new_payer_type === payer)
        return <DonutChart {...status} key={payer} title={`Switched to ${payerLabel(payer)} from…`}
          titleContent={<>Switched to <strong>{payerLabel(payer)}</strong> from…</>}
          valueLabel="Payer changes" centerMode="total"
          subtitle={`${scopeName} · Select a previous payer to view logs`}
          items={into.map(row => ({ label: payerLabel(row.previous_payer_type), value: row.changes }))
            .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))}
          onSelect={label => openLogs({
            'new-payer': [payerLabel(payer)], 'previous-payer': [label],
            category: ['Payer type'],
            ...(scope ? { 'facility-id': rows.flatMap(row => row.facility_ids) } : {}),
          })} />
      })}
    </div>
  </>
}
