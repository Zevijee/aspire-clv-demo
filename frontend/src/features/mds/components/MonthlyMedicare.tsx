import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { type TableColumn } from '../../../shared/components/Table'
import { AllFacilitiesModal } from '../../../shared/components/AllFacilitiesModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { CustomGroupingButton } from '../../../shared/components/CustomGroupingButton'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { useCustomGrouping } from '../../../shared/customGrouping'
import { useSearchParamFlag } from '../../../shared/hooks/useSearchParamFlag'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { getMonthlyMedicare, type FacilityMonthly, type MonthlyMedicareReport } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../utils/locationDrilldown'
import { LocationNavigation } from './LocationNavigation'

type Row = DrilldownRow<FacilityMonthly>
type Month = MonthlyMedicareReport['months'][number]
type Measure = 'census' | 'neutral' | 'actual' | 'revenue'

/** One month's -- or, given every month, the range's -- value of a measure at
 * this row's scope: its facilities summed first and divided once. Census is
 * average daily census, resident-days over days; rates are summed rates over
 * resident-days. Null when there is nothing to divide by. */
function value(row: Row, measure: Measure, months: Month[]) {
  let residentDays = 0, actual = 0, neutral = 0
  for (const facility of row.facilities) {
    for (const { month } of months) {
      const totals = facility.months[month]
      if (!totals) continue
      residentDays += totals.resident_days
      actual += totals.actual_rates
      neutral += totals.neutral_rates
    }
  }
  const days = months.reduce((total, month) => total + month.days, 0)
  if (measure === 'census') return days > 0 ? residentDays / days : null
  // Revenue for the day: every resident's daily rate summed, over the days.
  if (measure === 'revenue') return days > 0 ? actual / days : null
  if (residentDays === 0) return null
  return (measure === 'actual' ? actual : neutral) / residentDays
}

/** The highest or lowest month at this scope, and its value, across the
 * months that have one. The earlier month wins a tie. */
function extreme(row: Row, measure: Measure, months: Month[], pick: 'highest' | 'lowest') {
  let best: { month: string; amount: number } | null = null
  for (const month of months) {
    const amount = value(row, measure, [month])
    if (amount !== null && (!best || (pick === 'highest' ? amount > best.amount : amount < best.amount))) {
      best = { month: month.month, amount }
    }
  }
  return best
}

const money = (amount: number) => amount.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
// Daily revenue runs to millions: $4.65M reads where $4,650,000 would not fit an axis.
const millions = (amount: number) => `$${(amount / 1e6).toLocaleString(undefined,
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`
const census = (amount: number) => amount.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })

// The table's columns after the location: average, highest month and lowest
// month of each measure.
const metrics: [id: string, header: string, measure: Measure, kind: 'average' | 'highest' | 'lowest'][] = [
  ['census', 'Avg. daily census', 'census', 'average'],
  ['census_high', 'Highest month census', 'census', 'highest'],
  ['census_low', 'Lowest month census', 'census', 'lowest'],
  ['neutral', 'Avg. neutral rate', 'neutral', 'average'],
  ['neutral_high', 'Highest neutral rate', 'neutral', 'highest'],
  ['neutral_low', 'Lowest neutral rate', 'neutral', 'lowest'],
  ['actual', 'Avg. actual rate', 'actual', 'average'],
  ['actual_high', 'Highest actual rate', 'actual', 'highest'],
  ['actual_low', 'Lowest actual rate', 'actual', 'lowest'],
]

/** Monthly Medicare PDPM Trending: PDPM census and rates over a range of
 * months, drilled from state to facility, each as its average over the range
 * and its highest and lowest month. */
export function MonthlyMedicare() {
  const [params, setParams] = useReportSearchParams()
  const { start, end } = getReportMonthRange(params)
  const startMonth = start.format('YYYY-MM')
  const endMonth = end.format('YYYY-MM')
  // The drilldown location, kept in the URL (one drill= per level, in order).
  const path = params.getAll('drill')
  const setPath = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete('drill')
    next.forEach(name => updated.append('drill', name))
    // Drilling closes Show all facilities, in this same write.
    updated.delete('all_facilities')
    setParams(updated)
  }
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
  const months = data?.months ?? []
  const columns: TableColumn<Row>[] = [
    { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name :
        <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> },
    ...metrics.map(([id, header, measure, kind]): TableColumn<Row> => ({
      id, header, numeric: true,
      // Sorted by the value; a highest or lowest month shows which month it was.
      value: row => (kind === 'average' ? value(row, measure, months) : extreme(row, measure, months, kind)?.amount) ?? '—',
      format: (amount, row) => {
        if (typeof amount !== 'number') return amount
        const shown = measure === 'census' ? census(amount) : money(amount)
        const found = kind === 'average' ? null : extreme(row, measure, months, kind)
        // The value first, as in every other column; its month after it as a
        // small muted tag, so the two never read as one number.
        return found ? <span className="report-table__value-with-tag">{shown}
          <span className="report-table__tag">{dayjs(found.month).format('MMM YYYY')}</span></span> : shown
      },
      exportValue: row => {
        if (kind === 'average') return value(row, measure, months) ?? ''
        const found = extreme(row, measure, months, kind)
        return found ? `${dayjs(found.month).format('MMM YYYY')}: ${found.amount.toFixed(2)}` : ''
      },
    })),
  ]
  const loading = !data && !error
  const monthLabel = (month: string) => dayjs(month).format('MMMM YYYY')
  const partial = data && months.length && months[months.length - 1].days < dayjs(months[months.length - 1].month).daysInMonth()
    ? ` ${monthLabel(months[months.length - 1].month)} counts through ${data.census_date}.` : ''
  const subtitle = data ? 'Federal Medicare and Managed Medicare PDPM residents; Managed Medicare PPO pays per diem '
    + 'and is not included. Average daily census is PDPM resident-days over the days with census; a rate is '
    + 'summed daily rates over resident-days. Highest and lowest are the months with the highest and lowest '
    + `value at each location. Neutral rate is not adjusted for the facility's case mix; actual rate is what `
    + `the payer paid.${partial}` : ''
  const file = `${startMonth}-to-${endMonth}`
  // The trends follow the drilldown: each month's value at the scope shown,
  // its facilities summed first and divided once, as the table does. A bar
  // spans its month's days with census, so the tooltip shows them.
  const scopeRow: Row = { key: 'scope', name: '', path, facilities: rows.flatMap(row => row.facilities) }
  const scopeName = path.length ? path[path.length - 1] : grouping ? 'Custom grouping' : 'All locations'
  const monthBars = (measure: Measure) => months.flatMap(month => {
    const amount = value(scopeRow, measure, [month])
    return amount === null ? [] : [{ date: month.month,
      end_date: dayjs(month.month).add(month.days - 1, 'day').format('YYYY-MM-DD'), value: amount }]
  })

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} PDPM by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retryLoad}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-medicare-pdpm-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · PDPM by month, ${start.format('MMM YYYY')} to ${end.format('MMM YYYY')}`}
      subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retryLoad}
      csvFileName={`monthly-medicare-pdpm-facilities-${file}.csv`} />
    {/* Two to a row, on the same months, so a move in one reads against the
        others -- in Historical Medicare PDPM's order: census, the two rates,
        then daily revenue. The axes start near the lowest month, not at zero:
        each moves a few points on a large base. */}
    <div className="report-chart-grid">
      <LineChart title="PDPM census trending" valueLabel="Avg. daily census" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-primary)" baseline="fit"
        subtitle={`${scopeName}. Average daily PDPM census each month: its resident-days over its days.`}
        items={monthBars('census')} formatValue={amount => census(amount)}
        loading={loading} error={error} onRetry={retryLoad} />
      <LineChart title="Neutral rate trending" valueLabel="Avg. neutral rate" variant="bar" interval="month"
        height={320} barColor="var(--color-accent)" baseline="fit"
        subtitle={`${scopeName}. Average case-mix-neutral daily rate each month: the national per diem times the PDPM day factor.`}
        items={monthBars('neutral')} formatValue={money}
        loading={loading} error={error} onRetry={retryLoad} />
      <LineChart title="Actual rate trending" valueLabel="Avg. actual rate" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-quinary)" baseline="fit"
        subtitle={`${scopeName}. Average daily rate the payers paid each month, per resident-day.`}
        items={monthBars('actual')} formatValue={money}
        loading={loading} error={error} onRetry={retryLoad} />
      <LineChart title="Daily revenue trending" valueLabel="Avg. daily revenue" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-senary)" baseline="fit"
        subtitle={`${scopeName}. Total PDPM revenue for an average day each month: every resident's daily rate summed, over the month's days.`}
        items={monthBars('revenue')} formatValue={millions}
        loading={loading} error={error} onRetry={retryLoad} />
    </div>
  </>
}
