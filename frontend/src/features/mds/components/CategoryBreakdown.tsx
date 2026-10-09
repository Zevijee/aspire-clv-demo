import { useEffect, useState, type ReactNode } from 'react'
import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { LocationNavigation } from '../../../shared/components/LocationNavigation'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { StackedRankingChart } from '../../../shared/components/charts/StackedRankingChart'
import { getMedicareCategories, type CategoriesReport, type CategoryCounts, type FacilityCategories } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow, type Located } from '../../../shared/utils/locationDrilldown'

export const categories = [
  { id: 'primary-diagnosis', label: 'Primary Diagnosis' },
  { id: 'pt-ot', label: 'PT/OT' },
  { id: 'slp', label: 'SLP' },
  { id: 'speech-comorbidity', label: 'Speech Comorbidity' },
  { id: 'nursing', label: 'Nursing' },
  { id: 'nursing-category', label: 'Nursing Category' },
  { id: 'nta', label: 'NTA' },
  { id: 'depression', label: 'Depression' },
] as const

type Row = DrilldownRow<FacilityCategories>
// The Residents tab's filter for each level of a location path, in path order.
const residentLocationFilters = ['state', 'portfolio', 'region', 'facility']

/** One category's split of PDPM residents: which counts on each facility it
 * reads, and the parts in the order the report shows them, each with the one
 * colour it has wherever it appears. */
export type Breakdown = {
  field: 'primary_diagnosis' | 'pt_ot' | 'slp' | 'nursing' | 'nursing_category' | 'nta' | 'depression' | 'speech'
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
// The nursing clinical category, from the nursing letter: the same six names
// the PDPM Worksheet's Nursing offers. Colours as NTA's six bands.
const nursingCategory: Breakdown = {
  field: 'nursing_category', name: 'Nursing category', splitBy: 'nursing clinical category', slug: 'nursing-category',
  parts: [
    ['extensive_services', 'Extensive Services', 'var(--color-pdpm-major-joint)'],
    ['special_care_high', 'Special Care High', 'var(--color-pdpm-ortho)'],
    ['special_care_low', 'Special Care Low', 'var(--color-pdpm-acute-neuro)'],
    ['clinically_complex', 'Clinically Complex', 'var(--color-pdpm-medical-management)'],
    ['behavioral', 'Behavioral Symptoms and Cognitive Performance', 'var(--color-chart-series-secondary)'],
    ['reduced_physical_function', 'Reduced Physical Function', 'var(--color-chart-series-quaternary)'],
  ],
}

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
    ['slp_comorbidity', 'Comorbidity', 'var(--color-chart-series-secondary)'],
    ['mechanically_altered_diet', 'MAD', 'var(--color-pdpm-acute-neuro)'],
    ['swallowing_disorder', 'SD', 'var(--color-pdpm-medical-management)'],
  ],
}

// Every category button has one; the type makes a new button bring its breakdown.
export const breakdowns: Record<(typeof categories)[number]['id'], Breakdown> = {
  'primary-diagnosis': primaryDiagnosis, 'pt-ot': ptOt, slp, 'speech-comorbidity': speech, nursing, 'nursing-category': nursingCategory, nta, depression,
}

/** A facility's category counts: every category Medicare PDPM has, or only the
 * nursing and NTA ones Medicaid's two-letter code has. Every code has a nursing
 * letter, so the nursing categories always sum to the residents with a code. */
export type CategoryFacility = Partial<CategoryCounts> & { nursing_category: Record<string, number> }
export type CategoryId = (typeof categories)[number]['id']

/** How many in each part of one category at a location, summed over its
 * facilities; a category a facility does not carry counts as zero. */
export function categoryCount<Item extends Partial<CategoryCounts>>(row: DrilldownRow<Item>, breakdown: Breakdown, field: string) {
  return row.facilities.reduce((total, facility) =>
    total + ((facility[breakdown.field] as Record<string, number> | undefined)?.[field] ?? 0), 0)
}

/** One table column per part of the category, counting each location. Each
 * header carries its part's chart colour, so the table keys the chart. */
export function categoryColumns<Item extends Partial<CategoryCounts>>(breakdown: Breakdown): TableColumn<DrilldownRow<Item>>[] {
  return breakdown.parts.map(([field, header, color]): TableColumn<DrilldownRow<Item>> => ({
    id: field, header, marker: color, numeric: true, value: row => categoryCount(row, breakdown, field),
    format: value => typeof value === 'number' ? value.toLocaleString() : value,
  }))
}

/** Who a category view counts: residents in a bed, or stays in a range. */
export type CategoryUnit = { one: string; many: string }

/** One category's ranking chart and the chart's table view, over the
 * locations a drilldown shows; the drilldown table's headers key its colours. Every share is of those with a care code --
 * the only ones a category can count -- which the exclusive parts sum to and
 * the overlapping ones do not. Shared by every report that counts PDPM codes. */
export function CategoryCharts<Item extends Located & CategoryFacility>({ breakdown, rows, depth, scopeName, unit,
    population, fileSuffix, loading, error, onRetry, onSegmentSelect }: {
  breakdown: Breakdown
  /** The drilldown table's rows, one per location at this level. */
  rows: DrilldownRow<Item>[]
  depth: number
  /** Where the drilldown is, for the table view's title. */
  scopeName: string
  unit: CategoryUnit
  /** Whom the chart counts, ahead of "in each state": "PDPM residents with a care code on 2026-10-07". */
  population: string
  fileSuffix: string
  loading: boolean
  error: string | null
  onRetry: () => void
  /** A click on one location's part of a bar; leave out where there is nothing to open. */
  onSegmentSelect?: (row: DrilldownRow<Item>, partId: string) => void
}) {
  type Row = DrilldownRow<Item>
  const [showRankingTable, setShowRankingTable] = useState(false)
  const count = (row: Row, field: string) => categoryCount(row, breakdown, field)
  // With a care code: everyone in one nursing category, which every code has.
  const total = (row: Row) => row.facilities.reduce((sum, facility) =>
    sum + Object.values(facility.nursing_category).reduce((a, b) => a + b, 0), 0)
  const level = levels[depth].toLowerCase()
  // One bar per location, split into the category's parts, the most with a
  // care code first. The same counts as the chart table.
  const ranking = [...rows].sort((a, b) => total(b) - total(a) || a.name.localeCompare(b.name))
    .map(row => ({ label: row.name, total: total(row),
      values: Object.fromEntries(breakdown.parts.map(([field]) => [field, count(row, field)])) }))
  const split = breakdown.overlapping ? `with each ${breakdown.splitBy}` : `split by ${breakdown.splitBy}`
  const overlap = breakdown.overlapping ? `; one ${unit.one} can have several` : ''

  return <>
    <StackedRankingChart loading={loading} error={error} onRetry={onRetry}
      title={`${breakdown.name} by ${level}`} totalLabel={`${unit.many} with a care code`}
      subtitle={loading ? undefined : `${population} in each ${level}, ${split}, the most ${unit.many} first${overlap}.`
        + (breakdown.overlapping ? ' MAD is a mechanically altered diet, SD a swallowing disorder, '
          + 'Comorbidity an SLP-related comorbidity.' : '')}
      // The table above keys every colour in its column headers, so the chart
      // needs no legend: with twelve SLP groups one crowded the chart's header.
      hideLegend showValues series={breakdown.parts.map(([id, label, color]) => ({ id, label, color }))} items={ranking}
      onSegmentSelect={onSegmentSelect && ((label, partId) => {
        const row = rows.find(group => group.name === label)
        if (row) onSegmentSelect(row, partId)
      })}
      headerActions={<OpenViewButton kind="table" label="See in table view" onClick={() => setShowRankingTable(true)} />} />
    <FullScreenModal open={showRankingTable} onClose={() => setShowRankingTable(false)} destroyOnHidden
      title={`${breakdown.name} by ${level} · ${scopeName}`}>
      <div className="net-change-daily-modal__table">
        {/* The chart's numbers: the same locations, ranked by the same total. */}
        <Table<Row> title={`${breakdown.name} by ${level}`}
          subtitle={loading ? '' : `${population} in each ${level}, ${split}${overlap}.`}
          columns={[{ id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name }, ...categoryColumns<Item>(breakdown),
            { id: 'total', header: 'With care code', numeric: true, value: total,
              format: value => typeof value === 'number' ? value.toLocaleString() : value }]}
          rows={rows} getRowKey={row => row.key} initialSort={{ columnId: 'total', direction: 'descending' }}
          internalScroll stickyFirstColumn loading={loading} error={error} onRetry={onRetry}
          emptyMessage="No locations in this view."
          csvFileName={`${breakdown.slug}-ranking-${fileSuffix}.csv`} />
      </div>
    </FullScreenModal>
  </>
}

/** The category buttons, with the choice kept in the URL so a link or a
 * refresh keeps it. They go in the drilldown bar, which is sticky, so they stay
 * in reach however far the page scrolls. */
export function useCategoryControl(ids?: readonly CategoryId[], label = 'PDPM category') {
  const [params, setParams] = useReportSearchParams()
  // A report whose code carries fewer categories offers only those, in order.
  const offered = ids ? categories.filter(category => ids.includes(category.id)) : [...categories]
  const selected = offered.find(category => category.id === params.get('category')) ?? offered[0]
  const control = <SegmentedControl fullWidth separate tone="accent" label={label} options={offered} value={selected.id}
    onChange={id => {
      const next = new URLSearchParams(params)
      if (id === offered[0].id) next.delete('category')
      else next.set('category', id)
      setParams(next)
    }} />
  return { selected, breakdown: breakdowns[selected.id], control }
}

/** PDPM residents split by one category, drilled from state to facility: the
 * table's columns, the cards and the chart all follow the category. */
function CategoryDrilldown({ breakdown, categoryLabel, onOpenResidents, path, setPath, controls }: {
  breakdown: Breakdown; categoryLabel: string; path: string[]; setPath: (path: string[]) => void
  controls: ReactNode
  /** Open the Residents tab on one location path and one category part. */
  onOpenResidents: (locationPath: string[], part: string) => void
}) {
  const [data, setData] = useState<CategoriesReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    getMedicareCategories(controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The location, then how many residents in each part of the chosen category.
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    ...categoryColumns<FacilityCategories>(breakdown),
  ]
  const loading = !data && !error
  const retryLoad = () => setRetry(value => value + 1)
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const subtitle = data ? `Residents paid from their PDPM code on ${data.census_date}: Original Medicare, `
    + 'and Managed Medicare PDPM. Managed Medicare PPO pays per diem and is not included. '
    + 'Residents not yet assessed and coded in the first days of their Medicare stay are missing a care code '
    + `and counted in no ${breakdown.name.toLowerCase()} part.`
    + (breakdown.overlapping ? ' One resident can have several conditions, so the parts do not sum to the residents.' : '')
    : ''
  const day = data?.census_date ?? 'today'

  return <>
    {/* Every category shares one location path, so switching keeps where you are. */}
    <LocationNavigation path={path} setPath={setPath} controls={controls} />
    <DrilldownTable<Row> title={`${breakdown.name} by ${levels[depth].toLowerCase()}`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retryLoad}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`current-medicare-${breakdown.slug}-${day}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={path => setPath(path)}
      title={`All facilities · ${breakdown.name}, census on ${day}`} subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retryLoad}
      csvFileName={`current-medicare-${breakdown.slug}-facilities-${day}.csv`} />
    <CategoryCharts<FacilityCategories> breakdown={breakdown} rows={rows} depth={depth} scopeName={scopeName}
      unit={{ one: 'resident', many: 'residents' }}
      population={`PDPM residents with a care code on ${data?.census_date ?? ''}`}
      fileSuffix={day} loading={loading} error={error} onRetry={retryLoad}
      // A segment opens its residents: this location, this part, as the
      // Residents tab's "Category: part" filter names it.
      onSegmentSelect={(row, partId) => {
        const part = breakdown.parts.find(([field]) => field === partId)
        if (part) onOpenResidents(row.path, `${categoryLabel}: ${part[1]}`)
      }} />
  </>
}

/** The PDPM categories, one at a time. */
export function CategoryBreakdown() {
  const [params, setParams] = useReportSearchParams()
  const { selected, breakdown, control } = useCategoryControl()
  // The drilldown location, kept in the URL (one drill= per level, in order):
  // switching category keeps it -- drilled into Florida on Primary Diagnosis,
  // Nursing opens on Florida too -- and so does going to the Residents tab and
  // back, a refresh, or a shared link.
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write: a second write
    // from the same render would undo this one.
    updated.delete('all_facilities')
    setParams(updated)
  }
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
  return <CategoryDrilldown breakdown={breakdown} categoryLabel={selected.label}
    onOpenResidents={openResidents} path={path} setPath={setPath} controls={control} />
}
