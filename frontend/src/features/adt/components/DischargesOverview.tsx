import { useEffect, useMemo, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getDischargeOverview, type DischargeOverview } from '../api/discharges'
import { DischargesByDestination } from './DischargesByDestination'
import { DischargesByPayer } from './DischargesByPayer'
import { DischargesDailyTrend } from './DischargesDailyTrend'
import { getDischargeDrilldownRows, getDischargeTotal, type DischargeDrilldownRow } from '../utils/dischargesDrilldown'
import { dischargeLogsParams, type DischargeCount } from '../utils/dischargeLogsFilters'

import { matchesLocation, getLocationLevel, locationLevels, type LocationLevel } from '../utils/admissionsOverviewFilters'

const levels = ['State', 'Portfolio', 'Region', 'Facility']
const averageFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

export type DischargeSelection = { path: string[]; locations?: string[]; groupBy?: LocationLevel; payers: string[]; destinations: string[] }

export function DischargesOverview({ selection, onChange }: {
  selection: DischargeSelection; onChange: (selection: DischargeSelection) => void
}) {
  const [params, setParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = params.get('start_date') ?? defaults.startDate
  const endDate = params.get('end_date') ?? defaults.endDate
  const { path, payers, destinations } = selection
  const setPath = (path: string[]) => onChange({ ...selection, path })
  const setPayers = (payers: string[]) => onChange({ ...selection, payers })
  const setDestinations = (destinations: string[]) => onChange({ ...selection, destinations })
  const filters = useMemo(() => ({ payers, destinations, locations: selection.locations }), [payers, destinations, selection.locations])
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([startDate, endDate, filters, retry])
  const [response, setResponse] = useState<{ key: string; data: DischargeOverview } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void getDischargeOverview(startDate, endDate, controller.signal, filters)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [startDate, endDate, filters, requestKey])
  const result = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  const days = result?.days ?? 1
  const customLevel = selection.groupBy ?? getLocationLevel(selection.locations ?? []) ?? 'state'
  const depth = path.length || locationLevels.indexOf(customLevel)
  const clearCustomView = () => onChange({ ...selection, path: [], locations: [], groupBy: 'state' })
  const level = levels[depth]
  const selectedRows = (result?.items ?? []).filter((row) => matchesLocation({ ...row, facility: row.facility_name }, selection.locations ?? []))
  const rows = getDischargeDrilldownRows(selectedRows, path, days, depth)
  const countColumn = (id: DischargeCount, header: string): TableColumn<DischargeDrilldownRow> => ({
    id, header, numeric: true, value: (row) => row[id],
    format: (_, row) => row[id] === 0 ? '0' : <button type="button" className="drilldown-table__link"
      aria-label={`View ${row.name} ${header.toLowerCase()} logs`}
      onClick={() => setParams(dischargeLogsParams(params, row.facilityNames, filters, id))}>
      {row[id].toLocaleString('en-US')}
    </button>,
  })
  const columns: TableColumn<DischargeDrilldownRow>[] = [
    { id: 'name', header: level, isRowHeader: true, filterable: true, value: (row) => row.name,
      format: (_, row) => row.isTotal || depth === 3 ? row.name
        : <button className="drilldown-table__link" type="button"
            aria-label={`View ${row.name} ${levels[depth + 1].toLowerCase()} discharges`}
            onClick={() => setPath(row.path)}>{row.name}</button> },
    countColumn('total', 'Total discharges'),
    { id: 'average-los', header: 'Average LOS (days)', numeric: true,
      value: (row) => row.total && Number.isFinite(row.totalLosDays) ? row.totalLosDays / row.total : 'N/A',
      format: (value) => typeof value === 'number' ? averageFormat.format(value) : value },
    { id: 'prior', header: 'Prior-period discharges', numeric: true, value: (row) => row.prior },
    { id: 'change', header: 'Discharges vs prior', numeric: true, value: (row) => row.change,
      change: { favorable: 'decrease' } },
    countColumn('ama', 'AMA discharges'),
    countColumn('hospitalTransfers', 'Hospital transfers'),
  ]
  return <>
    <DrilldownNavigation ariaLabel="Discharges drill-down"
      locationView={{ groupBy: customLevel, selectedCount: selection.locations?.length ?? 0,
        selectionLevel: getLocationLevel(selection.locations ?? []),
        onReturn: () => setPath([]), onClear: clearCustomView }}
      activeFilters={[...(payers.length ? ['payer'] : []), ...(destinations.length ? ['destination'] : [])]}
      onClearFilter={(filter) => filter === 'payer' ? setPayers([]) : setDestinations([])} items={[
      ...path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
        onSelect: () => setPath(path.slice(0, index + 1)) })),
    ]} />
    <Table key={JSON.stringify(path)} columns={columns} rows={rows} getRowKey={(row) => row.key}
      title={`${level} Discharge Metrics`}
      subtitle={`${path.length ? path.join(' / ') : 'All states'} · Compared with the immediately preceding period of equal length`}
      loading={result === null && error === null} error={error} onRetry={() => setRetry((count) => count + 1)}
      initialSort={{ columnId: 'total', direction: 'descending' }}
      getFooterRow={(visibleRows) => getDischargeTotal(visibleRows, days)}
      csvFileName={`discharges-${level.toLowerCase()}-${startDate}-to-${endDate}.csv`}
      emptyMessage="No facilities match this view." />
    <div className="report-chart-grid">
      <DischargesByDestination startDate={startDate} endDate={endDate} path={path}
        locations={selection.locations} payers={payers} selected={destinations} onChange={setDestinations} />
      <DischargesByPayer startDate={startDate} endDate={endDate} path={path}
        locations={selection.locations} destinations={destinations} selected={payers} onChange={setPayers} />
    </div>
    <DischargesDailyTrend startDate={startDate} endDate={endDate} path={path} filters={filters} />
  </>
}
