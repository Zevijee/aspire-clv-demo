import { useEffect, useState, type ReactNode } from 'react'
import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { StackedRankingChart } from '../../../shared/components/charts/StackedRankingChart'
import { Kpis } from '../../../shared/components/Kpis'
import { getMedicareOverview, type FacilityOverview, type OverviewReport } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../utils/locationDrilldown'

const categories = [
  { id: 'primary-diagnosis', label: 'Primary Diagnosis' },
  { id: 'pt-ot', label: 'PT/OT' },
  { id: 'slp', label: 'SLP' },
  { id: 'speech-comorbidity', label: 'Speech Comorbidity' },
  { id: 'nursing', label: 'Nursing' },
  { id: 'nta', label: 'NTA' },
  { id: 'depression', label: 'Depression' },
] as const

type Row = DrilldownRow<FacilityOverview>
// The Residents tab's filter for each level of a location path, in path order.
const residentLocationFilters = ['state', 'portfolio', 'region', 'facility']
type Summed = 'federal' | 'managed' | 'actual_rates' | 'neutral_rates' | 'resident_days' | 'no_score'
  | 'no_score_days'

function sum(row: Row, field: Summed) {
  return row.facilities.reduce((total, facility) => total + facility[field], 0)
}
// Sums at this scope divided once by its residents: never an average of
// facility averages.
function metric(row: Row, field: string): number | null {
  const residents = sum(row, 'federal') + sum(row, 'managed')
  if (field === 'residents') return residents
  if (field === 'neutral_rate') return residents > 0 ? sum(row, 'neutral_rates') / residents : null
  if (field === 'actual_rate') return residents > 0 ? sum(row, 'actual_rates') / residents : null
  if (field === 'los') return residents > 0 ? sum(row, 'resident_days') / residents : null
  if (field === 'missing_los') {
    const missing = sum(row, 'no_score')
    return missing > 0 ? sum(row, 'no_score_days') / missing : null
  }
  return sum(row, field as Summed)
}

// The location table's columns, after the location itself.
const metrics: [id: string, header: string, kind: 'count' | 'rate' | 'days'][] = [
  ['residents', 'PDPM residents', 'count'], ['federal', 'Federal Medicare', 'count'],
  ['managed', 'Managed Medicare PDPM', 'count'], ['no_score', 'Missing care code', 'count'],
  ['missing_los', 'Avg. LOS, missing care code', 'days'],
  ['neutral_rate', 'Neutral rate', 'rate'], ['actual_rate', 'Actual rate', 'rate'],
  ['los', 'Avg. length of stay', 'days'],
]
function formatMetric(value: number | string, kind: 'count' | 'rate' | 'days') {
  if (typeof value !== 'number') return value
  if (kind === 'rate') return value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  const digits = kind === 'days' ? 1 : 0
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** One category's split of PDPM residents: which counts on each facility it
 * reads, and the parts in the order the report shows them, each with the one
 * colour it has wherever it appears. */
type Breakdown = {
  field: 'primary_diagnosis' | 'pt_ot' | 'slp' | 'nursing' | 'nta' | 'depression' | 'speech'
  /** Chart and table titles, e.g. "Primary diagnosis by state". */
  name: string
  /** What the bars are split by, for the chart's subtitle. */
  splitBy: string
  /** CSV file name prefix. */
  slug: string
  parts: [field: string, header: string, color: string][]
  /** The parts overlap, one resident in several, so a stacked bar can run
   * past the residents; shares are always of the PDPM residents. */
  overlapping?: boolean
}

// The PT/OT clinical categories, the first letter of the PDPM code.
const primaryDiagnosis: Breakdown = {
  field: 'primary_diagnosis', name: 'Primary diagnosis', splitBy: 'clinical category', slug: 'primary-diagnosis',
  parts: [
    ['major_joint', 'Major Joint', 'var(--color-pdpm-major-joint)'],
    ['ortho', 'Ortho / Ortho Surgery', 'var(--color-pdpm-ortho)'],
    ['acute_neuro', 'Acute Neuro / Non-Ortho', 'var(--color-pdpm-acute-neuro)'],
    ['medical_management', 'Medical Management', 'var(--color-pdpm-medical-management)'],
  ],
}

// The PT/OT function score band of the same letter, lowest function first, in
// the same four colours as primary diagnosis.
const ptOt: Breakdown = {
  field: 'pt_ot', name: 'PT/OT function score', splitBy: 'PT/OT function score', slug: 'pt-ot-function-score',
  parts: [
    ['score_0_5', '0-5', 'var(--color-pdpm-major-joint)'],
    ['score_6_9', '6-9', 'var(--color-pdpm-ortho)'],
    ['score_10_23', '10-23', 'var(--color-pdpm-acute-neuro)'],
    ['score_24', '24', 'var(--color-pdpm-medical-management)'],
  ],
}

// The SLP group, the second letter of the code: how many speech conditions
// (0-3) by how many swallowing needs (0-2), A through L. Hue follows the speech
// count, shade the swallowing count.
const speechCounts = [0, 1, 2, 3]
const swallowingCounts = [0, 1, 2]
const slp: Breakdown = {
  field: 'slp', name: 'SLP', splitBy: 'SLP group', slug: 'slp',
  parts: speechCounts.flatMap(speechCount => swallowingCounts.map((swallowing): Breakdown['parts'][number] => [
    `speech_${speechCount}_swallowing_${swallowing}`, `${speechCount} speech, ${swallowing} swallowing`,
    `var(--color-pdpm-slp-${speechCount}-${swallowing})`])),
}

// The nursing function score band, from the score stored on the assessment,
// lowest function first.
const nursing: Breakdown = {
  field: 'nursing', name: 'Nursing function score', splitBy: 'nursing function score', slug: 'nursing-function-score',
  parts: [
    ['score_0_5', '0-5', 'var(--color-pdpm-major-joint)'],
    ['score_6_14', '6-14', 'var(--color-pdpm-ortho)'],
    ['score_15_16', '15-16', 'var(--color-pdpm-acute-neuro)'],
  ],
}

// The NTA comorbidity points band, the fourth letter of the code, fewest points
// first: the four category colours, then the chart's green and red.
const nta: Breakdown = {
  field: 'nta', name: 'NTA comorbidity points', splitBy: 'NTA comorbidity points', slug: 'nta-points',
  parts: [
    ['points_0', '0', 'var(--color-pdpm-major-joint)'],
    ['points_1_2', '1-2', 'var(--color-pdpm-ortho)'],
    ['points_3_5', '3-5', 'var(--color-pdpm-acute-neuro)'],
    ['points_6_8', '6-8', 'var(--color-pdpm-medical-management)'],
    ['points_9_11', '9-11', 'var(--color-chart-series-secondary)'],
    ['points_12_plus', '12+', 'var(--color-chart-series-quaternary)'],
  ],
}

// Signs of depression, a yes / no flag on the assessment.
const depression: Breakdown = {
  field: 'depression', name: 'Depression', splitBy: 'depression', slug: 'depression',
  parts: [
    ['yes', 'Yes', 'var(--color-pdpm-major-joint)'],
    ['no', 'No', 'var(--color-pdpm-ortho)'],
  ],
}

// The SLP conditions, from flags on the assessment. A resident can have several.
const speech: Breakdown = {
  field: 'speech', name: 'Speech comorbidity', splitBy: 'SLP condition', slug: 'speech-comorbidity',
  overlapping: true,
  parts: [
    ['cognitive_impairment', 'Cognitive Ability', 'var(--color-pdpm-major-joint)'],
    ['acute_neuro', 'Acute Neuro Primary', 'var(--color-pdpm-ortho)'],
    ['mechanically_altered_diet', 'MAD', 'var(--color-pdpm-acute-neuro)'],
    ['swallowing_disorder', 'SD', 'var(--color-pdpm-medical-management)'],
  ],
}

// Every category button has one; the type makes a new button bring its breakdown.
const breakdowns: Record<(typeof categories)[number]['id'], Breakdown> = {
  'primary-diagnosis': primaryDiagnosis, 'pt-ot': ptOt, slp, 'speech-comorbidity': speech, nursing, nta, depression,
}

/** The drilldown bar every category shares: its breadcrumbs follow the one
 * location path, so switching category keeps where you are. */
function CategoryNavigation({ path, setPath, controls }: {
  path: string[]; setPath: (path: string[]) => void; controls: ReactNode
}) {
  const depth = Math.min(path.length, 3)
  return <DrilldownNavigation locationView={{
    groupBy: 'state', selectedCount: 0,
    onReturn: () => setPath([]),
    onClear: () => setPath([]),
  }} items={path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
    onSelect: () => setPath(path.slice(0, index + 1)) }))}
    level={{ current: depth + 1, total: 4, label: levels[depth] }} controls={controls} />
}

/** PDPM residents split by one category, drilled from state to facility. The
 * location table is the same for every category; the cards, chart and chart
 * table follow the category. */
function CategoryDrilldown({ breakdown, categoryLabel, onOpenResidents, path, setPath, controls }: {
  breakdown: Breakdown; categoryLabel: string; path: string[]; setPath: (path: string[]) => void
  controls: ReactNode
  /** Open the Residents tab on one location path and one category part. */
  onOpenResidents: (locationPath: string[], part: string) => void
}) {
  const [data, setData] = useState<OverviewReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showRankingTable, setShowRankingTable] = useState(false)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getMedicareOverview(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])

  const { depth, rows } = groupByLocation(data?.items ?? [], path)
  const count = (row: Row, field: string) => row.facilities.reduce((total, facility) =>
    total + ((facility[breakdown.field] as Record<string, number>)[field] ?? 0), 0)
  const nameColumn: TableColumn<Row> = { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
  // The location table: residents, payer split, rates and stay length.
  const columns: TableColumn<Row>[] = [
    nameColumn,
    ...metrics.map(([id, header, kind]): TableColumn<Row> => ({
      id, header, numeric: true, value: row => metric(row, id) ?? '—', format: value => formatMetric(value, kind),
    })),
  ]
  // The chart's table: residents in each part of the category.
  const categoryColumns: TableColumn<Row>[] = breakdown.parts.map(([field, header]): TableColumn<Row> => ({
    id: field, header, numeric: true, value: row => count(row, field),
    format: value => typeof value === 'number' ? value.toLocaleString() : value,
  }))
  const loading = !data && !error
  // One bar per location, split into the category's parts, the location with
  // the most residents with a care code first. The same counts as the chart
  // table. Every share is of the residents with a care code -- the only
  // ones a category can count -- which the exclusive parts sum to and the
  // overlapping ones do not.
  const total = (row: Row) => (metric(row, 'residents') ?? 0) - sum(row, 'no_score')
  const ranking = [...rows].sort((a, b) => total(b) - total(a) || a.name.localeCompare(b.name))
    .map(row => ({ label: row.name, total: total(row),
      values: Object.fromEntries(breakdown.parts.map(([field]) => [field, count(row, field)])) }))
  // The totals of whatever the table shows, so the cards always equal its Total
  // row: everyone at the top, one state or region once drilled in.
  const scope: Row = { key: 'scope', name: '', path, facilities: rows.flatMap(row => row.facilities) }
  const scopeTotal = total(scope)
  const scopeName = path.length ? path[path.length - 1] : 'All locations'
  const share = (value: number) => scopeTotal > 0
    ? `${(value / scopeTotal * 100).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : '—'
  const kpis = [
    ...breakdown.parts.map(([field, header, color]) => ({
      // A band's bare number ("6-9") needs its measure beside it on a card.
      header: breakdown.field === 'pt_ot' || breakdown.field === 'nursing' ? `Function score ${header}`
        : breakdown.field === 'nta' ? `NTA points ${header}`
        : breakdown.field === 'depression' ? `Depression: ${header}` : header, marker: color, value: count(scope, field).toLocaleString(),
      trend: { tone: 'neutral' as const, value: share(count(scope, field)), label: 'of residents with a care code' },
    })),
  ]
  const subtitle = data ? `Residents paid from their PDPM code on ${data.census_date}: Original Medicare, `
    + 'and Managed Medicare PDPM. Managed Medicare PPO pays per diem and is not included. '
    + 'Missing care code is residents not yet assessed and coded in the first days of their Medicare stay; '
    + 'the categories below count only residents with a care code. '
    + "Neutral rate is not adjusted for the facility's case mix. Actual rate is what the payer pays." : ''

  return <>
    <CategoryNavigation path={path} setPath={setPath} controls={controls} />
    <DrilldownTable<Row> title={`${levels[depth]} PDPM residents`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} />}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicare-${data?.census_date ?? 'today'}.csv`} />
    <Kpis stack items={kpis} loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      title={data ? `All facilities · PDPM residents on ${data.census_date}` : 'All facilities'} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      csvFileName={`current-medicare-facilities-${data?.census_date ?? 'today'}.csv`} />
    <StackedRankingChart loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
      title={`${breakdown.name} by ${levels[depth].toLowerCase()}`} totalLabel="residents with a care code"
      subtitle={data ? `PDPM residents with a care code on ${data.census_date} in each ${levels[depth].toLowerCase()}, `
        + (breakdown.overlapping ? `with each ${breakdown.splitBy}, the most residents first; one resident `
          + 'can have several. MAD is a mechanically altered diet, SD a swallowing disorder.'
          : `split by ${breakdown.splitBy}, the most residents first.`) : undefined}
      // The KPI cards above key every colour, so the chart needs no legend.
      hideLegend series={breakdown.parts.map(([id, label, color]) => ({ id, label, color }))} items={ranking}
      // A segment opens its residents: this location, this part, as the
      // Residents tab's "Category: part" filter names it.
      onSegmentSelect={(label, partId) => {
        const row = rows.find(group => group.name === label)
        const part = breakdown.parts.find(([field]) => field === partId)
        if (row && part) onOpenResidents(row.path, `${categoryLabel}: ${part[1]}`)
      }}
      headerActions={<OpenViewButton kind="table" label="See in table view" onClick={() => setShowRankingTable(true)} />} />
    <FullScreenModal open={showRankingTable} onClose={() => setShowRankingTable(false)} destroyOnHidden
      title={`${breakdown.name} by ${levels[depth].toLowerCase()} · ${scopeName}`}>
      <div className="net-change-daily-modal__table">
        {/* The chart's numbers: the same locations, ranked by the same total. */}
        <Table<Row> title={`${breakdown.name} by ${levels[depth].toLowerCase()}`}
          subtitle={data ? `PDPM residents with a care code on ${data.census_date} in each ${levels[depth].toLowerCase()}, `
            + (breakdown.overlapping ? `with each ${breakdown.splitBy}; one resident can have several.`
              : `split by ${breakdown.splitBy}.`) : ''}
          columns={[{ ...nameColumn, format: undefined }, ...categoryColumns,
            { id: 'total', header: 'With care code', numeric: true, value: total,
              format: value => typeof value === 'number' ? value.toLocaleString() : value }]}
          rows={rows} getRowKey={row => row.key} initialSort={{ columnId: 'total', direction: 'descending' }}
          internalScroll stickyFirstColumn loading={loading} error={error} onRetry={() => setRetry(value => value + 1)}
          emptyMessage="No locations in this view."
          csvFileName={`${breakdown.slug}-ranking-${data?.census_date ?? 'today'}.csv`} />
      </div>
    </FullScreenModal>
  </>
}

/** The PDPM categories, one at a time. The choice lives in the URL, so a link
 * or a refresh keeps it. */
export function CategoryBreakdown() {
  const [params, setParams] = useReportSearchParams()
  const selected = categories.find(category => category.id === params.get('category')) ?? categories[0]
  // Held here, above the categories, so switching category keeps the location:
  // drilled into Florida on Primary Diagnosis, Nursing opens on Florida too.
  const [path, setPath] = useState<string[]>([])
  // The category buttons live in the drilldown bar, which is sticky, so they
  // stay in reach however far the page scrolls.
  const control = <SegmentedControl fullWidth separate tone="accent" label="PDPM category" options={categories} value={selected.id}
    onChange={id => {
      const next = new URLSearchParams(params)
      if (id === categories[0].id) next.delete('category')
      else next.set('category', id)
      setParams(next)
    }} />
  // One drilldown for every category, so switching between them keeps its
  // loaded data rather than fetching again.
  // The Residents tab reads its opening filters from residents_* parameters,
  // as the ADT logs read logs_*: the location path by level, then the part.
  const openResidents = (locationPath: string[], part: string) => {
    const next = new URLSearchParams(params)
    for (const key of [...next.keys()]) {
      if (key.startsWith('residents_')) next.delete(key)
    }
    next.set('view', 'residents')
    locationPath.forEach((name, index) => next.set(`residents_${residentLocationFilters[index]}`, name))
    next.set('residents_pdpm-category', part)
    setParams(next)
  }
  return <CategoryDrilldown breakdown={breakdowns[selected.id]} categoryLabel={selected.label}
    onOpenResidents={openResidents} path={path} setPath={setPath} controls={control} />
}
