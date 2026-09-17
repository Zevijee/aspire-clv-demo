import { useEffect, useMemo, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { NetChangeDailyTrend } from './NetChangeDailyTrend'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getNetChange, type NetChangeReport } from '../api/netChange'
import { formatPayerType } from '../api/admissions'
import { getNetChangeRows, getNetChangeTotal, type NetChangeRow } from '../utils/netChangeDrilldown'
import { matchesLocation, getLocationLevel, locationLevels } from '../utils/admissionsOverviewFilters'

const levels = ['State', 'Portfolio', 'Region', 'Facility']

export function NetChangeOverview() {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const days = Math.max(1, Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86400000) + 1)
  const payerKey = JSON.stringify([...new Set(params.getAll('net_payer'))].sort())
  const selectedPayers = useMemo(() => JSON.parse(payerKey) as string[], [payerKey])
  function setPayer(payer?: string) {
    const next = new URLSearchParams(params)
    const payers = payer ? selectedPayers.includes(payer)
      ? selectedPayers.filter(value => value !== payer) : [...selectedPayers, payer] : []
    next.delete('net_payer')
    payers.forEach(value => next.append('net_payer', value))
    setParams(next)
  }
  const pathKey = JSON.stringify(params.getAll('net_scope').slice(0, 4))
  const path = useMemo(() => JSON.parse(pathKey) as string[], [pathKey])
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([startDate, endDate, selectedPayers, retry])
  const [response, setResponse] = useState<{ key: string; data: NetChangeReport } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getNetChange(startDate, endDate, controller.signal, selectedPayers)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, selectedPayers, key])
  const result = response?.key === key ? response.data : null
  const error = failure?.key === key ? failure.message : null
  const locations = params.getAll('net_location')
  const groupBy = locationLevels.find(value => value === params.get('net_level')) ?? getLocationLevel(locations) ?? 'state'
  const depth = path.length || locationLevels.indexOf(groupBy)
  const level = levels[Math.min(depth, 3)]
  const previousDates = response ? JSON.parse(response.key) as unknown[] : []
  const retainedResult = previousDates[0] === startDate && previousDates[1] === endDate ? response?.data : null
  const selectedFacilities = ((result ?? retainedResult)?.items ?? []).filter(row =>
    matchesLocation({ ...row, facility: row.facility_name }, locations))
  const rows = getNetChangeRows(selectedFacilities, path, depth)
  function setPath(nextPath: string[]) {
    const next = new URLSearchParams(params)
    next.delete('net_scope')
    nextPath.forEach((part) => next.append('net_scope', part))
    setParams(next)
  }
  const columns: TableColumn<NetChangeRow>[] = [
    { id: 'name', header: level, isRowHeader: true, value: (row) => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button className="drilldown-table__link" type="button" onClick={() => setPath(row.path)}>
          {row.name}
        </button> },
    { id: 'net_change', header: 'Net change', numeric: true, value: (row) => row.net_change,
      change: { favorable: 'increase' } },
    ...(['opening_census', 'admissions', 'discharges', 'closing_census'] as const).map((id): TableColumn<NetChangeRow> => ({
      id, header: { opening_census: 'Open census', closing_census: 'Close census',
        admissions: 'Admissions', discharges: 'Discharges' }[id],
      numeric: true, value: (row) => row[id] ?? '—',
      format: (value) => typeof value === 'number' ? value.toLocaleString() : value,
    })),
    ...(selectedPayers.length > 0 ? (['payer_changes_in', 'payer_changes_out'] as const).map((id): TableColumn<NetChangeRow> => ({
      id, header: id === 'payer_changes_in' ? 'Payer in' : 'Payer out',
      numeric: true, value: row => row[id] ?? 0,
    })) : []),
    { id: 'payer_changes', header: 'Payer changes', numeric: true, value: row => row.payer_changes ?? 0,
      format: value => Number(value).toLocaleString() },
    ...([
      { id: 'average_net_change_per_day', header: 'Net/day', denominator: () => days },
      ...(depth < 3 ? [
      { id: 'average_net_change_per_facility', header: 'Net/facility', denominator: (row: NetChangeRow) => row.facilityCount },
      { id: 'average_net_change_per_facility_per_day', header: 'Net/facility/day', denominator: (row: NetChangeRow) => row.facilityCount * days },
      ] : []),
    ]).map(({ id, header, denominator }): TableColumn<NetChangeRow> => ({
      id, header, numeric: true,
      value: (row) => denominator(row) > 0 ? row.net_change / denominator(row) : 0,
      format: (value) => Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      change: { favorable: 'increase' },
    })),
    { id: 'prior_net_change', header: 'Prior net', numeric: true,
      value: (row) => row.prior_net_change ?? '—', change: { favorable: 'increase' } },
  ]
  const visibleColumns = columns.filter(column =>
    !column.id.startsWith('average_net_change_') && column.id !== 'prior_net_change')
  return <>
    <DrilldownNavigation ariaLabel="Net change drill-down"
      locationView={{ groupBy, selectedCount: locations.length, selectionLevel: getLocationLevel(locations),
        onReturn: () => setPath([]), onClear: () => {
          const next = new URLSearchParams(params)
          for (const key of ['net_scope', 'net_location', 'net_level']) next.delete(key)
          setParams(next)
        } }}
      activeFilters={selectedPayers.map(formatPayerType)} onClearFilter={label => {
        const payer = selectedPayers.find(value => formatPayerType(value) === label)
        if (payer) setPayer(payer)
      }}
      items={[
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} />
    <Table key={JSON.stringify([pathKey, locations, groupBy])} title={`${level} net change`}
      subtitle={`Net change is close census minus open census.${selectedPayers.length > 0 ? ' Includes payer changes in and out.' : ''}`}
      columns={visibleColumns} rows={rows} getRowKey={(row) => row.key}
      stickyFirstColumn retainRowsWhileLoading initialSort={{ columnId: 'net_change', direction: 'descending' }}
      getFooterRow={getNetChangeTotal} loading={result === null && error === null} error={error}
      onRetry={() => setRetry((count) => count + 1)}
      csvFileName={`net-change-${level.toLowerCase()}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No facilities match this location." />
    {/* <DivergingBarChart title={`Net census change by ${level.toLowerCase()}`}
      subtitle="Close census compared with open census"
      items={rows.map((row) => ({ id: row.key, label: row.name, value: row.net_change }))}
      loading={result === null && error === null} error={error}
      onRetry={() => setRetry((count) => count + 1)} /> */}
    <NetChangeDailyTrend />
  </>
}
