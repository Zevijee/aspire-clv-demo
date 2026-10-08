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
import { getMonthlyMedicaid, type FacilityMonthlyMedicaid, type MonthlyMedicaidReport } from '../api'
import { drilldownLevels as levels, facilityRows, groupByLocation, type DrilldownRow } from '../../../shared/utils/locationDrilldown'
import { LocationNavigation, locationColumn as nameColumn } from '../../../shared/components/LocationNavigation'
import { scopeNote, useDrillPath } from './CurrentMedicaid'

type Row = DrilldownRow<FacilityMonthlyMedicaid>
type Month = MonthlyMedicaidReport['months'][number]
type Measure = 'census' | 'census_days' | 'actual' | 'revenue'

/** One month's -- or, given every month, the range's -- value of a measure at
 * this row's scope, as Monthly Medicare PDPM Trending computes it: facilities
 * summed first and divided once. Null when there is nothing to divide by. */
function value(row: Row, measure: Measure, months: Month[]) {
  let residentDays = 0, actual = 0
  for (const facility of row.facilities) {
    for (const { month } of months) {
      const totals = facility.months[month]
      if (!totals) continue
      residentDays += totals.resident_days
      actual += totals.actual_rates
    }
  }
  const days = months.reduce((total, month) => total + month.days, 0)
  if (measure === 'census') return days > 0 ? residentDays / days : null
  if (measure === 'census_days') return residentDays
  if (measure === 'revenue') return actual
  return residentDays > 0 ? actual / residentDays : null
}

/** The highest or lowest month at this scope, and its value. The earlier month wins a tie. */
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
const millions = (amount: number) => `$${(amount / 1e6).toLocaleString(undefined,
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`
const census = (amount: number) => amount.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })

// Monthly Medicare PDPM Trending's columns less the neutral rate.
const metrics: [id: string, header: string, measure: Measure, kind: 'average' | 'highest' | 'lowest'][] = [
  ['census', 'Avg. daily census', 'census', 'average'],
  ['census_high', 'Highest month census', 'census', 'highest'],
  ['census_low', 'Lowest month census', 'census', 'lowest'],
  ['actual', 'Avg. actual rate', 'actual', 'average'],
  ['actual_high', 'Highest actual rate', 'actual', 'highest'],
  ['actual_low', 'Lowest actual rate', 'actual', 'lowest'],
]

/** Monthly Medicaid Trending: Texas Medicaid census, rate and revenue over a
 * range of months, drilled from Texas to facility, each as its average over
 * the range and its highest and lowest month. */
export function MonthlyMedicaid() {
  const [params] = useReportSearchParams()
  const { start, end } = getReportMonthRange(params)
  const startMonth = start.format('YYYY-MM')
  const endMonth = end.format('YYYY-MM')
  const { path, setPath } = useDrillPath()
  const [data, setData] = useState<MonthlyMedicaidReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [showFacilities, setShowFacilities] = useSearchParamFlag('all_facilities')
  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    setData(null)
    getMonthlyMedicaid(startMonth, endMonth, controller.signal)
      .then(body => { if (!controller.signal.aborted) setData(body) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [startMonth, endMonth, retry])
  const retryLoad = () => setRetry(count => count + 1)

  const { grouping } = useCustomGrouping()
  const { depth, rows } = groupByLocation(data?.items ?? [], path, grouping)
  const months = data?.months ?? []
  const columns: TableColumn<Row>[] = [
    nameColumn<FacilityMonthlyMedicaid>(depth, path, setPath),
    ...metrics.map(([id, header, measure, kind]): TableColumn<Row> => ({
      id, header, numeric: true,
      // Sorted by the value; a highest or lowest month shows which month it was.
      value: row => (kind === 'average' ? value(row, measure, months) : extreme(row, measure, months, kind)?.amount) ?? '—',
      format: (amount, row) => {
        if (typeof amount !== 'number') return amount
        const shown = measure === 'census' ? census(amount) : money(amount)
        const found = kind === 'average' ? null : extreme(row, measure, months, kind)
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
  const last = months[months.length - 1]
  const partial = data && last && last.days < dayjs(last.month).daysInMonth()
    ? ` ${dayjs(last.month).format('MMMM YYYY')} counts through ${data.census_date}.` : ''
  const subtitle = data ? `${scopeNote} Average daily census is Medicaid resident-days over the days with census; `
    + 'the rate is summed daily rates over resident-days, what Medicaid paid. Highest and lowest are the months '
    + `with the highest and lowest value at each location.${partial}` : ''
  const file = `${startMonth}-to-${endMonth}`
  // The trends follow the drilldown, each month's value at the scope shown. A
  // bar spans its month's days with census, so the tooltip shows them.
  const scopeRow: Row = { key: 'scope', name: '', path, facilities: rows.flatMap(row => row.facilities) }
  const scopeName = grouping && !path.length ? 'Custom grouping' : path[path.length - 1] ?? 'Texas'
  const monthBars = (measure: Measure) => months.flatMap(month => {
    const amount = value(scopeRow, measure, [month])
    return amount === null ? [] : [{ date: month.month,
      end_date: dayjs(month.month).add(month.days - 1, 'day').format('YYYY-MM-DD'), value: amount }]
  })
  const chartStatus = { loading, error, onRetry: retryLoad }

  return <>
    <LocationNavigation path={path} setPath={setPath} />
    <DrilldownTable<Row> title={`${levels[depth]} Medicaid by month`} columns={columns} rows={rows}
      getRowKey={row => row.key} initialSort={{ columnId: 'name', direction: 'ascending' }}
      loading={loading} error={error} onRetry={retryLoad}
      getFooterRow={visible => ({ key: 'total', name: 'Total', path: [], isTotal: true,
        facilities: visible.flatMap(row => row.facilities) })}
      subtitle={subtitle}
      headerActions={<><OpenViewButton kind="facilities" label="Show all facilities" onClick={() => setShowFacilities(true)} /><CustomGroupingButton onApply={() => setPath([])} /></>}
      emptyMessage="No facilities match this view."
      csvFileName={`monthly-medicaid-${file}.csv`} />
    <AllFacilitiesModal<Row> open={showFacilities} onClose={() => setShowFacilities(false)}
      onSelect={next => setPath(next)}
      title={`All facilities · Medicaid by month, ${start.format('MMM YYYY')} to ${end.format('MMM YYYY')}`}
      subtitle={subtitle}
      rows={facilityRows(data?.items ?? [])} columns={columns.slice(1)} getRowKey={row => row.key}
      getName={row => row.name} getPath={row => [row.path[0], row.path[1], row.path[2]]}
      loading={loading} error={error} onRetry={retryLoad}
      csvFileName={`monthly-medicaid-facilities-${file}.csv`} />
    {/* Monthly Medicare PDPM Trending's charts less the neutral rate, three to
        a row on the same months. The axes start near the lowest month. */}
    <div className="report-chart-grid report-chart-grid--three-columns">
      <LineChart title="Medicaid census trending" valueLabel="Census days" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-primary)" baseline="fit" showDailyAverage
        subtitle={`${scopeName}. Total Medicaid census days each month: every resident's days in a bed. Hover a month for its average daily census.`}
        items={monthBars('census_days')} formatValue={amount => amount.toLocaleString(undefined, { maximumFractionDigits: 1 })}
        {...chartStatus} />
      <LineChart title="Actual rate trending" valueLabel="Avg. actual rate" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-quinary)" baseline="fit"
        subtitle={`${scopeName}. Average daily rate Medicaid paid each month, per resident-day.`}
        items={monthBars('actual')} formatValue={money} {...chartStatus} />
      <LineChart title="Monthly revenue trending" valueLabel="Revenue" variant="bar" interval="month"
        height={320} barColor="var(--color-chart-series-senary)" baseline="fit" showDailyAverage
        subtitle={`${scopeName}. Total Medicaid revenue each month: what Medicaid paid for every resident's days. Hover a month for its average per day.`}
        items={monthBars('revenue')} formatValue={millions} {...chartStatus} />
    </div>
  </>
}
