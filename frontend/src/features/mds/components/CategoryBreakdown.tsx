import { useEffect, useState, type ReactNode } from 'react'
import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import type { TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { StackedRankingChart } from '../../../shared/components/charts/StackedRankingChart'
import { Kpis } from '../../../shared/components/Kpis'
import { getMedicareCategories, type CategoriesReport, type FacilityCategories, type PrimaryDiagnosis } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../utils/locationDrilldown'

const categories = [
  { id: 'primary-diagnosis', label: 'Primary Diagnosis' },
  { id: 'speech-comorbidity', label: 'Speech Comorbidity' },
  { id: 'cognitive-ability', label: 'Cognitive Ability' },
  { id: 'nursing', label: 'Nursing' },
  { id: 'nta', label: 'NTA' },
  { id: 'depression', label: 'Depression' },
  { id: 'missing-code', label: 'Missing Code' },
] as const

type Row = DrilldownRow<FacilityCategories>

// The PT/OT clinical categories, in the order the report shows them, each with
// the one colour it has wherever it appears.
const primaryDiagnosis: [field: keyof PrimaryDiagnosis, header: string, color: string][] = [
  ['major_joint', 'Major Joint', 'var(--color-pdpm-major-joint)'],
  ['ortho', 'Ortho / Ortho Surgery', 'var(--color-pdpm-ortho)'],
  ['acute_neuro', 'Acute Neuro / Non-Ortho', 'var(--color-pdpm-acute-neuro)'],
  ['medical_management', 'Medical Management', 'var(--color-pdpm-medical-management)'],
]

/** PDPM residents by clinical category, drilled from state to facility. */
function PrimaryDiagnosisDrilldown({ controls }: { controls: ReactNode }) {
  const [data, setData] = useState<CategoriesReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [path, setPath] = useState<string[]>([])
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getMedicareCategories(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])

  const { depth, rows } = groupByLocation(data?.items ?? [], path)
  const count = (row: Row, field: keyof PrimaryDiagnosis) =>
    row.facilities.reduce((total, facility) => total + facility.primary_diagnosis[field], 0)
  const nameColumn: TableColumn<Row> = { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
  const columns: TableColumn<Row>[] = [
    nameColumn,
    ...primaryDiagnosis.map(([field, header]): TableColumn<Row> => ({
      id: field, header, numeric: true, value: row => count(row, field),
      format: value => typeof value === 'number' ? value.toLocaleString() : value,
    })),
  ]
  const loading = !data && !error
  // One bar per location, split into its four categories, the location with the
  // most PDPM residents first. The same counts as the table.
  const total = (row: Row) => primaryDiagnosis.reduce((sum, [field]) => sum + count(row, field), 0)
  const ranking = [...rows].sort((a, b) => total(b) - total(a) || a.name.localeCompare(b.name))
    .map(row => ({ label: row.name,
      values: Object.fromEntries(primaryDiagnosis.map(([field]) => [field, count(row, field)])) }))
  // The totals of whatever the table shows, so the cards always equal its Total
  // row: everyone at the top, one state or region once drilled in.
  const scope: Row = { key: 'scope', name: '', path, facilities: rows.flatMap(row => row.facilities) }
  const scopeTotal = total(scope)
  const scopeName = path.length ? path[path.length - 1] : 'All locations'
  const share = (value: number) => scopeTotal > 0
    ? `${(value / scopeTotal * 100).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : '—'
  const kpis = [
    { header: 'PDPM residents', value: scopeTotal.toLocaleString(),
      trend: { tone: 'neutral' as const, value: '', label: scopeName } },
    ...primaryDiagnosis.map(([field, header, color]) => ({
      header, marker: color, value: count(scope, field).toLocaleString(),
      trend: { tone: 'neutral' as const, value: share(count(scope, field)), label: 'of PDPM residents' },
    })),
  ]
  const subtitle = data ? `PDPM residents on ${data.census_date} by clinical category, the first letter of their `
    + 'PDPM code. Major Joint includes spinal surgery.' : ''

  return <>
    <DrilldownNavigation locationView={{
      groupBy: 'state', selectedCount: 0,
      onReturn: () => setPath([]),
      onClear: () => setPath([]),
    }} items={path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
      onSelect: () => setPath(path.slice(0, index + 1)) }))}
      level={{ current: depth + 1, total: 4, label: levels[depth] }} controls={controls} />
    <DrilldownTable<Row> title={`${levels[depth]} primary diagnosis`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`primary-diagnosis-${data?.census_date ?? 'today'}.csv`} />
    <Kpis items={kpis} loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      title={data ? `All facilities · primary diagnosis on ${data.census_date}` : 'All facilities'} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      csvFileName={`primary-diagnosis-facilities-${data?.census_date ?? 'today'}.csv`} />
    <StackedRankingChart loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      title={`Primary diagnosis by ${levels[depth].toLowerCase()}`} totalLabel="PDPM residents"
      series={primaryDiagnosis.map(([id, label, color]) => ({ id, label, color }))} items={ranking}
      onSelect={depth < 3 ? label => {
        const row = rows.find(group => group.name === label)
        if (row) setPath(row.path)
      } : undefined} />
  </>
}

/** The PDPM categories, one at a time. The choice lives in the URL, so a link
 * or a refresh keeps it. Categories other than primary diagnosis are still to
 * be built. */
export function CategoryBreakdown() {
  const [params, setParams] = useReportSearchParams()
  const selected = categories.find(category => category.id === params.get('category')) ?? categories[0]
  // The category buttons live in the drilldown bar, which is sticky, so they
  // stay in reach however far the page scrolls.
  const control = <SegmentedControl fullWidth label="PDPM category" options={categories} value={selected.id}
    onChange={id => {
      const next = new URLSearchParams(params)
      if (id === categories[0].id) next.delete('category')
      else next.set('category', id)
      setParams(next)
    }} />
  return selected.id === 'primary-diagnosis' ? <PrimaryDiagnosisDrilldown controls={control} /> : <>
    {/* Categories without content yet keep the same bar, so the buttons do not move. */}
    <DrilldownNavigation items={[]} controls={control} locationView={{
      groupBy: 'state', selectedCount: 0, onReturn: () => {}, onClear: () => {} }} />
    <section className="report-placeholder" aria-label={`${selected.label} content`} />
  </>
}
