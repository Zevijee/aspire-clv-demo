import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { SegmentedControl } from '../../../shared/components/SegmentedControl'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { useLocationSheets } from '../../../shared/locationSheets'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { getMonthlyMedicare, type FacilityMonthly, type MonthlyMedicareReport } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../../../shared/utils/locationDrilldown'
import { LocationNavigation } from '../../../shared/components/LocationNavigation'

type Row = DrilldownRow<FacilityMonthly>
type Month = MonthlyMedicareReport['months'][number]
// The category buttons, in order; each id is a key of a month's categories.
const categories = [
  { id: 'depression', label: 'Depression', what: 'residents with depression on their PDPM assessment' },
  { id: 'medical_management', label: 'Medical Management',
    what: 'residents in the PT/OT clinical category Medical Management' },
  { id: 'slp_sa', label: 'SA (SLP)', what: 'residents in SLP group SA: no speech condition and no swallowing need' },
  { id: 'behavioral', label: 'Behavioral',
    what: 'residents in the nursing clinical category Behavioral Symptoms and Cognitive Performance' },
  { id: 'reduced_physical_function', label: 'Reduced Physical Function',
    what: 'residents in the nursing clinical category Reduced Physical Function' },
  { id: 'nursing_gg_15_16', label: 'Nursing GG 15–16', what: 'residents with a nursing function score of 15 or 16' },
] as const
type Category = typeof categories[number]

/** Residents coded in the months given at this row's scope, its facilities
 * summed: those coded with the category, and every resident coded. Each
 * resident counts in the month their code took effect only, so months add. */
function coded(row: Row, category: Category, months: Month[]) {
  let withCategory = 0, all = 0
  for (const facility of row.facilities) {
    for (const { month } of months) {
      const totals = facility.months[month]
      if (!totals) continue
      withCategory += totals.category_residents[category.id] ?? 0
      all += totals.coded_residents
    }
  }
  return { withCategory, without: all - withCategory, all, share: all > 0 ? withCategory / all : null }
}

/** The month with the most or fewest residents coded with the category at
 * this scope. The earlier month wins a tie. */
function extreme(row: Row, category: Category, months: Month[], pick: 'highest' | 'lowest') {
  let best: { month: string; amount: number } | null = null
  for (const month of months) {
    const amount = coded(row, category, [month]).withCategory
    if (!best || (pick === 'highest' ? amount > best.amount : amount < best.amount)) best = { month: month.month, amount }
  }
  return best
}

const percent = (amount: number) => amount.toLocaleString(undefined, { style: 'percent', minimumFractionDigits: 1,
  maximumFractionDigits: 1 })
const count = (amount: number) => amount.toLocaleString(undefined, { maximumFractionDigits: 1 })

/** Monthly Medicare PDPM Trending's Category breakdown: one PDPM category at a
 * time, chosen by its button: the residents coded in the range with it and
 * without it, drilled from state to facility, and the residents coded with it
 * each month. */
export function MonthlyMedicareCategories({ initialPath }: { initialPath?: string[] } = {}) {
  const [params, setParams] = useReportSearchParams()
  const { start, end } = getReportMonthRange(params)
  const startMonth = start.format('YYYY-MM')
  const endMonth = end.format('YYYY-MM')
  const category = categories.find(entry => entry.id === params.get('category')) ?? categories[0]
  // The drilldown location, kept in the URL (one drill= per level, in order),
  // or the location the export's copy is drawn at.
  const path = initialPath ?? params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
  // The category in the URL so a link or a refresh keeps it; the first is the default.
  const control = <SegmentedControl fullWidth separate tone="accent" label="PDPM category" options={categories}
    value={category.id} onChange={id => {
      const next = new URLSearchParams(params)
      if (id === categories[0].id) next.delete('category')
      else next.set('category', id)
      setParams(next)
    }} />
  const [data, setData] = useState<MonthlyMedicareReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    setData(null)
    getMonthlyMedicare(startMonth, endMonth, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startMonth, endMonth, retry])
  const retryLoad = () => setRetry(count => count + 1)

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  // The Excel export's sheet for each location in the table, this report drilled into it.
  useLocationSheets(() => path.length === 4 ? [] : rows.map(row => ({ name: row.name,
    render: () => <MonthlyMedicareCategories initialPath={row.path} /> })))
  const months = data?.months ?? []
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    { id: 'with', header: `With ${category.label}`, numeric: true,
      value: row => coded(row, category, months).withCategory, format: amount => count(Number(amount)) },
    { id: 'without', header: `Without ${category.label}`, numeric: true,
      value: row => coded(row, category, months).without, format: amount => count(Number(amount)) },
    { id: 'all', header: 'Total coded', numeric: true,
      value: row => coded(row, category, months).all, format: amount => count(Number(amount)) },
    { id: 'share', header: `% with ${category.label}`, numeric: true,
      value: row => coded(row, category, months).share ?? '—',
      format: amount => typeof amount === 'number' ? percent(amount) : amount },
    { id: 'average', header: `Avg. per month with ${category.label}`, numeric: true,
      value: row => months.length ? coded(row, category, months).withCategory / months.length : '—',
      format: amount => typeof amount === 'number' ? count(amount) : amount },
    ...(['highest', 'lowest'] as const).map((kind): TableColumn<Row> => ({
      id: kind, header: kind === 'highest' ? 'Highest month' : 'Lowest month', numeric: true,
      // Sorted by the count; the tag shows which month it was.
      value: row => extreme(row, category, months, kind)?.amount ?? '—',
      format: (amount, row) => {
        const found = extreme(row, category, months, kind)
        if (typeof amount !== 'number' || !found) return amount
        // The count first, as in every other column; its month after it as a
        // small muted tag, so the two never read as one number.
        return <span className="report-table__value-with-tag">{count(amount)}
          <span className="report-table__tag">{dayjs(found.month).format('MMM YYYY')}</span></span>
      },
      exportValue: row => {
        const found = extreme(row, category, months, kind)
        return found ? `${dayjs(found.month).format('MMM YYYY')}: ${found.amount}` : ''
      },
    })),
  ]
  const loading = !data && !error
  const monthLabel = (month: string) => dayjs(month).format('MMMM YYYY')
  const partial = data && months.length && months[months.length - 1].days < dayjs(months[months.length - 1].month).daysInMonth()
    ? ` ${monthLabel(months[months.length - 1].month)} counts through ${data.census_date}.` : ''
  const subtitle = data ? `${category.label}: ${category.what}. Each PDPM resident is counted once, in the `
    + `month their PDPM code was coded, with ${category.label} or without it; Total coded is both. Federal Medicare `
    + 'and Managed Medicare PDPM; Managed Medicare PPO pays per diem and is not included. Highest and lowest are '
    + `the months with the most and fewest coded with ${category.label}.${partial}` : ''
  const file = `${category.id.replace(/_/g, '-')}-${startMonth}-to-${endMonth}`
  // The trend follows the drilldown: the scope shown, its facilities summed.
  const scopeRow: Row = { key: 'scope', name: '', path, facilities: rows.flatMap(row => row.facilities) }
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  // Each month's residents coded with the category at the scope shown; the
  // tooltip splits that month's coded residents with and without it.
  const residentBars = months.map(month => {
    const { withCategory, without, all, share } = coded(scopeRow, category, [month])
    return { date: month.month, end_date: dayjs(month.month).add(month.days - 1, 'day').format('YYYY-MM-DD'),
      value: withCategory, details: [
        { label: `Without ${category.label}`, value: count(without) },
        { label: 'Total coded', value: count(all) },
        { label: `% with ${category.label}`, value: share === null ? '—' : percent(share) },
      ] }
  })

  return <>
    <LocationNavigation path={path} setPath={setPath} controls={control} />
    <DrilldownTable<Row> title={`${category.label} by ${levels[depth].toLowerCase()}`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retryLoad}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-medicare-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · ${category.label} by month, ${start.format('MMM YYYY')} to ${end.format('MMM YYYY')}`}
      subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retryLoad}
      csvFileName={`monthly-medicare-facilities-${file}.csv`} />
    <LineChart title={`${category.label} residents trending`} valueLabel={`With ${category.label}`} variant="bar"
      interval="month" height={440} barColor="var(--color-chart-series-primary)" baseline="fit"
      subtitle={`${scopeName}. Residents coded with ${category.label} each month, counted in the month they were coded only. Hover a month for those coded without it and the total.`}
      items={residentBars} formatValue={amount => amount.toLocaleString()}
      loading={loading} error={error} onRetry={retryLoad} />
  </>
}
