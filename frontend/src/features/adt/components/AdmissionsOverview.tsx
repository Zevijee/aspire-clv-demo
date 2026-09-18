import { useState } from 'react'
import dayjs from 'dayjs'
import { Modal } from 'antd'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DataState } from '../../../shared/components/DataState'
import { DrilldownNavigation, type DrilldownBreadcrumb } from '../../../shared/components/DrilldownNavigation'
import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { groupTrendPeriods, trendBlockSize } from '../../../shared/utils/trendPeriods'
import { useAdmissionsOverview, useAdmissionsReferences } from '../hooks/useAdmissionsOverview'
import { payerCode, payerLabel, selectionParameters, type HospitalCount, type SummaryLocation } from '../api/admissionsOverview'
import { getLocationLevel, type OverviewSelection } from '../utils/admissionsOverviewFilters'
import type { DrilldownScope } from '../utils/admissionsDrilldown'

type Row = SummaryLocation & { prior: number | null; change: number | null; isTotal?: boolean }

export function AdmissionsOverview({ selection, onChangeSelection }: {
  selection: OverviewSelection
  onChangeSelection: (selection: OverviewSelection) => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaults.startDate
  const endDate = searchParams.get('end_date') ?? defaults.endDate
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const priorEnd = dayjs(startDate).subtract(1, 'day').format('YYYY-MM-DD')
  const priorStart = dayjs(startDate).subtract(days, 'day').format('YYYY-MM-DD')
  const { scope, sources } = selection
  const payers = selection.payers.map(payerCode)
  const customLevel = selection.groupBy ?? getLocationLevel(selection.locations ?? [])
  const level = scope === null ? customLevel ?? 'state' : scope.portfolio === undefined ? 'portfolio' : scope.region === undefined ? 'region' : 'facility'
  const detail = scope?.facility !== undefined
  const references = useAdmissionsReferences()
  const parameters = references.data ? selectionParameters(selection, references.data, level).toString() : null
  const current = useAdmissionsOverview(startDate, endDate, parameters)
  const previous = useAdmissionsOverview(priorStart, priorEnd, parameters)
  const status = {
    loading: references.loading || current.loading,
    error: references.error ?? current.error,
    onRetry: references.error ? references.onRetry : current.onRetry,
  }
  const [hospitalSelection, setHospitalSelection] = useState<{ row: Row; key: string } | null>(null)
  const selectionKey = JSON.stringify([startDate, endDate, parameters])
  const hospitalRow = hospitalSelection?.key === selectionKey ? hospitalSelection.row : null
  const priorRows = new Map(previous.data?.locations.map(row => [row.id, row.admissions]))
  const rows: Row[] = (current.data?.locations ?? []).map(row => {
    const prior = previous.data ? priorRows.get(row.id) ?? 0 : null
    return { ...row, prior, change: prior === null ? null : row.admissions - prior }
  })
  const scopeName = scope?.facility ?? scope?.region ?? scope?.portfolio ?? scope?.state ?? 'All selected locations'
  const navigate = (next: DrilldownScope) => onChangeSelection({ ...selection, scope: next })
  const setPayers = (values: string[]) => onChangeSelection({ ...selection, payers: values })
  const setSources = (values: string[]) => onChangeSelection({ ...selection, sources: values })
  const breadcrumbs: DrilldownBreadcrumb[] = []
  if (scope) {
    breadcrumbs.push({ id: 'state', label: scope.state, onSelect: () => navigate({ state: scope.state }) })
    if (scope.portfolio !== undefined) breadcrumbs.push({ id: 'portfolio', label: scope.portfolio,
      onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio }) })
    if (scope.region !== undefined) breadcrumbs.push({ id: 'region', label: scope.region,
      onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio, region: scope.region }) })
    if (scope.facility !== undefined) breadcrumbs.push({ id: 'facility', label: scope.facility })
  }
  function drillInto(row: Row) {
    const path = Object.fromEntries(row.path.map(part => [part.level, part.name]))
    navigate({ state: path.state, ...(path.portfolio ? { portfolio: path.portfolio } : {}),
      ...(path.region ? { region: path.region } : {}), ...(path.facility ? { facility: path.facility } : {}) })
  }
  function openLogs(row: Row, readmissions = false, hospital?: string) {
    const params = new URLSearchParams(searchParams)
    for (const key of [...params.keys()]) if (key.startsWith('logs_')) params.delete(key)
    params.set('view', 'logs')
    params.set('start_date', startDate)
    params.set('end_date', endDate)
    row.facility_ids.forEach(id => params.append('logs_facility-id', id))
    payers.forEach(payer => params.append('logs_payer', payer))
    const selectedSources = hospital ? ['Hospital'] : sources
    selectedSources.forEach(source => params.append('logs_source-type', source))
    if (readmissions) params.set('logs_readmission', 'true')
    if (hospital) params.set('logs_admission-source', hospital)
    setHospitalSelection(null)
    setSearchParams(params)
  }
  function total(visible: Row[]): Row | null {
    if (visible.length < 2) return null
    const hospitals = new Map<string, number>()
    visible.forEach(row => row.hospitals.forEach(h => hospitals.set(h.hospital_name, (hospitals.get(h.hospital_name) ?? 0) + h.admissions)))
    const admissions = visible.reduce((sum, row) => sum + row.admissions, 0)
    const prior = visible.some(row => row.prior === null) ? null : visible.reduce((sum, row) => sum + row.prior!, 0)
    return { id: 'total', name: 'Total', level, path: [], isTotal: true, admissions,
      prior, change: prior === null ? null : admissions - prior,
      readmissions: visible.reduce((sum, row) => sum + row.readmissions, 0),
      readmissions_30_day: visible.reduce((sum, row) => sum + row.readmissions_30_day, 0),
      average_per_day: admissions / days, referring_hospitals: hospitals.size,
      facility_ids: [...new Set(visible.flatMap(row => row.facility_ids))],
      hospitals: [...hospitals].map(([hospital_name, count]) => ({ hospital_name, admissions: count })) }
  }
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: level[0].toUpperCase() + level.slice(1), isRowHeader: true, value: row => row.name,
      format: (_, row) => {
        const name = <span className="admissions-explorer__entity"><strong>{row.name}</strong></span>
        return row.isTotal || detail ? name :
          <button type="button" className="admissions-explorer__drill" onClick={() => drillInto(row)}>{name}</button>
      } },
    ...(['admissions', 'readmissions'] as const).map(metric => ({ id: metric,
      header: metric === 'admissions' ? 'Total admissions' : 'Readmissions', numeric: true,
      initialSortDirection: 'descending' as const, value: (row: Row) => row[metric],
      format: (value: string | number, row: Row) => <button type="button"
        className="admissions-explorer__drill admissions-explorer__drill--count"
        aria-label={`View ${metric} for ${row.name} in Logs`} onClick={() => openLogs(row, metric === 'readmissions')}>{value.toLocaleString()}</button> })),
    { id: 'prior', header: 'Prior-period admissions', numeric: true, value: row => row.prior ?? '—',
      format: value => value.toLocaleString() },
    { id: 'change', header: 'Admissions vs Prior', numeric: true, value: row => row.change ?? '—', change: { favorable: 'increase' } },
    { id: 'hospitals', header: 'Referring hospitals', numeric: true, value: row => row.referring_hospitals,
      format: (value, row) => <button type="button" aria-haspopup="dialog"
        className="admissions-explorer__drill admissions-explorer__drill--count"
        aria-label={`View referring hospitals for ${row.name}`}
        onClick={() => setHospitalSelection({ row, key: selectionKey })}>{value.toLocaleString()}</button> },
  ]
  const hospitalColumns: TableColumn<HospitalCount>[] = [
    { id: 'hospital', header: 'Referring hospital', isRowHeader: true, value: row => row.hospital_name },
    { id: 'admissions', header: 'Admissions', numeric: true, value: row => row.admissions,
      format: (value, row) => <button type="button" className="admissions-explorer__drill admissions-explorer__drill--count"
        onClick={() => { if (hospitalRow) openLogs(hospitalRow, false, row.hospital_name) }}>{value.toLocaleString()}</button> },
  ]
  const blockSize = trendBlockSize(startDate, endDate)
  const trend = groupTrendPeriods((current.data?.daily ?? []).map(row => ({ date: row.date, value: row.admissions })), startDate, blockSize)
  return <>
    <Modal open={hospitalRow !== null} onCancel={() => setHospitalSelection(null)} footer={null} centered
      title={`Referring hospitals · ${hospitalRow?.name ?? ''}`} width="min(720px, calc(100vw - 32px))" destroyOnHidden>
      <div className="report-detail-modal__table"><Table internalScroll searchable title="Hospital admissions"
        subtitle="Admissions from each hospital in the selected period" columns={hospitalColumns}
        rows={hospitalRow?.hospitals ?? []} getRowKey={row => row.hospital_name}
        initialSort={{ columnId: 'admissions', direction: 'descending' }}
        csvFileName={`referring-hospitals-${startDate}-to-${endDate}.csv`} emptyMessage="No referring hospitals match these dates and filters." /></div>
    </Modal>
    <DrilldownNavigation ariaLabel="Admissions drill-down" items={breadcrumbs}
      locationView={{ groupBy: customLevel ?? 'state', selectedCount: selection.locations?.length ?? 0,
        selectionLevel: getLocationLevel(selection.locations ?? []), onReturn: () => navigate(null),
        onClear: () => onChangeSelection({ ...selection, scope: null, locations: [], groupBy: 'state' }) }}
      activeFilters={[...(payers.length ? ['payer'] : []), ...(sources.length ? ['source'] : [])]}
      onClearFilter={filter => { if (filter === 'payer') setPayers([]); if (filter === 'source') setSources([]) }} />
    {previous.error && !status.error && <DataState label="Prior period" error={`Prior period: ${previous.error}`} onRetry={previous.onRetry} />}
    <Table {...status} key={JSON.stringify([scope, selection.locations, selection.groupBy])} columns={columns} rows={rows}
      getRowKey={row => row.id} getFooterRow={total} initialSort={{ columnId: 'admissions', direction: 'descending' }}
      title={`${level[0].toUpperCase() + level.slice(1)} Admissions Metrics`}
      subtitle={`${scopeName} · ${detail ? 'Metrics and charts for this facility.' : 'Select a location to explore its admissions.'}`}
      csvFileName={`admissions-${level}-${startDate}-to-${endDate}.csv`} emptyMessage="No locations match this view." />
    <div className="admissions-dashboard">
      <BarChartRanking {...status} title="Admissions by Source Type" subtitle="Click sources to filter the report"
        categoryLabel="Admission source type" valueLabel="Admissions"
        items={(current.data?.by_source ?? []).map(row => ({ label: row.source_type, value: row.admissions }))
          .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))}
        selectedLabels={sources} onClear={() => setSources([])}
        onSelect={value => setSources(sources.includes(value) ? sources.filter(item => item !== value) : [...sources, value])} />
      <DonutChart {...status} title="Admissions by payer" subtitle="Click payers to filter the report"
        items={(current.data?.by_payer ?? []).map(row => ({ label: payerLabel(row.payer_type), value: row.admissions }))}
        selectedLabels={payers.map(payerLabel)} onClear={() => setPayers([])} onSelect={label => {
          const value = payerCode(label)
          setPayers(payers.includes(value) ? payers.filter(item => item !== value) : [...payers, value])
        }} />
    </div>
    <LineChart {...status} items={trend} title={blockSize === 1 ? 'Daily Admissions' : 'Admissions trend'}
      valueLabel="Admissions" variant="bar" height={400}
      subtitle={blockSize === 1 ? 'Total admissions each day' : `Total admissions per ${blockSize}-day period. The tooltip shows the exact dates and day count.`} />
  </>
}
