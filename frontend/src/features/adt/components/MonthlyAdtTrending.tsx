import dayjs from 'dayjs'
import { MonthlyAdtFilters } from './MonthlyAdtFilters'
import { useState } from 'react'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useSearchParams } from 'react-router-dom'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { DailyChangeChart } from '../../../shared/components/charts/DailyChangeChart'
import { useMonthlyAdt, type MonthlyMovement } from '../hooks/useMonthlyAdt'
import { monthlyFilter, type MonthlyTab } from '../api/monthlyAdt'
import { MonthlyAdtLocations } from './MonthlyAdtLocations'
import { AdmissionsOverviewModal, type AdmissionsMonthSelection } from './AdmissionsOverviewModal'

type Row = MonthlyMovement
const titles: Record<MonthlyTab, string> = { admissions: 'Admissions', discharges: 'Discharges', 'net-change': 'Net change' }

/** Monthly ADT Trending on one page: the locations table, then admissions and
 * discharges side by side and net change beneath them. Each chart reads its own
 * monthly table and narrows by its own filter, as the three were when they were
 * separate tabs. */
export function MonthlyAdtTrending() {
  const [admissionsMonth, setAdmissionsMonth] = useState<AdmissionsMonthSelection | null>(null)
  const [path, setPath] = useState<string[]>([])
  const [params] = useSearchParams()
  const { start, end } = getReportMonthRange(params)
  const lastDay = end.isSame(dayjs(), 'month') ? dayjs() : end.endOf('month')
  const range = { startDate: start.format('YYYY-MM-DD'), endDate: lastDay.format('YYYY-MM-DD') }
  const openMonth = (tab: MonthlyTab) => (item: { date: string; end_date?: string }) => setAdmissionsMonth({
    start: item.date, end: item.end_date ?? item.date, path, payers: params.getAll('monthly_payer'), report: tab })
  return <>
    <AdmissionsOverviewModal month={admissionsMonth} onClose={() => setAdmissionsMonth(null)} />
    <MonthlyAdtLocations {...range} path={path} setPath={setPath} />
    <div className="report-chart-grid">
      <MonthlyTrend tab="admissions" path={path} range={range} onSelect={openMonth('admissions')} />
      <MonthlyTrend tab="discharges" path={path} range={range} onSelect={openMonth('discharges')} />
    </div>
    <MonthlyTrend tab="net-change" path={path} range={range} onSelect={openMonth('net-change')} />
  </>
}

/** One view's monthly chart and its table view: admissions or discharges as
 * bars, net change as signed change. */
function MonthlyTrend({ tab, path, range, onSelect }: {
  tab: MonthlyTab; path: string[]; range: { startDate: string; endDate: string }
  onSelect: (item: { date: string; end_date?: string }) => void
}) {
  const [showTable, setShowTable] = useState(false)
  const [params] = useSearchParams()
  const { start, end } = getReportMonthRange(params)
  const filter = monthlyFilter[tab as keyof typeof monthlyFilter]
  const filterValues = filter ? params.getAll(filter.search) : []
  // The API groups by month from each view's own monthly rollup, so nothing is
  // bucketed here.
  const daily = useMonthlyAdt({ ...range, payers: params.getAll('monthly_payer'), path, tab, filterValues })
  const rows: Row[] = daily.months
  const label = titles[tab]
  const monthToDate = end.isSame(dayjs(), 'month') ? ' Current month is month to date.' : ''
  const filterNote = filterValues.length ? ` ${filter.label} ${filterValues.join(', ')}.` : ''
  const netColumns: TableColumn<Row>[] = [
    { id: 'value', header: 'Net change', numeric: true, value: row => row.value, change: { favorable: 'increase' } },
    ...(['opening_census', 'admissions', 'discharges', 'closing_census'] as const).map(id => ({
      id, header: { opening_census: 'Open census', admissions: 'Admissions', discharges: 'Discharges', closing_census: 'Close census' }[id],
      numeric: true, value: (row: Row) => row[id],
    })),
    ...(daily.hasPayers ? (['payer_changes_in', 'payer_changes_out'] as const).map(id => ({
      id, header: id === 'payer_changes_in' ? 'Payer in' : 'Payer out', numeric: true, value: (row: Row) => row[id],
    })) : []),
  ]
  const dailyMetric = tab === 'net-change' ? 'value' : tab
  const tableColumns: TableColumn<Row>[] = [
    { id: 'date', header: 'Month', isRowHeader: true, value: row => row.date,
      format: (_, row) => dayjs(row.date).format('MMM YYYY') },
    ...(tab === 'net-change' ? netColumns : [
      { id: tab, header: label, numeric: true, value: (row: Row) => row[tab] },
      { id: 'average', header: 'Average per day', numeric: true,
        value: (row: Row) => row[tab] / (dayjs(row.end_date).diff(dayjs(row.date), 'day') + 1),
        format: (value: string | number) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) },
    ]),
    ...[true, false].map((high): TableColumn<Row> => {
      const extreme = (row: Row) => row.days.length
        ? (high ? Math.max : Math.min)(...row.days.map(day => day[dailyMetric])) : 0
      return {
        id: high ? 'highest_day' : 'lowest_day', header: high ? 'Highest day' : 'Lowest day', numeric: true,
        value: extreme, change: tab === 'net-change' ? { favorable: 'increase' } : undefined,
        format: (_, row) => {
          if (!row.days.length) return '—'
          const value = extreme(row)
          const dates = row.days.filter(day => day[dailyMetric] === value).map(day => dayjs(day.date).format('MMM D, YYYY'))
          return <span className="report-table__value-with-tag" title={dates.join(', ')}>
            {value.toLocaleString(undefined, { signDisplay: tab === 'net-change' ? 'exceptZero' : 'auto' })}
            <span className="report-table__tag">{dates[0]}{dates.length > 1 ? ` +${dates.length - 1}` : ''}</span></span>
        },
      }
    }),
  ]
  const tableButton = <OpenViewButton kind="table" label="See in table view" onClick={() => setShowTable(true)} />
  const status = { loading: daily.loading, error: daily.error, onRetry: daily.onRetry }
  return <>
    {tab === 'net-change'
      ? <DailyChangeChart title="Monthly net change" onSelect={onSelect} headerActions={tableButton}
          subtitle={`Close census compared with open census each month.${monthToDate} Click a month to open its overview.`}
          items={rows} interval="month" height={400} {...status} />
      : <LineChart title={`Monthly ${label.toLowerCase()}`} onSelect={onSelect} headerActions={tableButton}
          subtitle={`Total ${label.toLowerCase()} per calendar month.${filterNote}${monthToDate} Click a month to open its overview.`}
          items={rows.map(row => ({ date: row.date, end_date: row.end_date, value: row[tab] }))}
          variant="bar" interval="month" height={360} showDailyAverage valueLabel={label}
          barColor={tab === 'admissions' ? 'var(--color-table-change-favorable)' : 'var(--color-table-change-adverse)'}
          {...status} />}
    <FullScreenModal open={showTable} onClose={() => setShowTable(false)} destroyOnHidden
      title={`Monthly ${label.toLowerCase()}: ${start.format('MMM YYYY')} to ${end.format('MMM YYYY')}`}>
      <div className="net-change-daily-modal__table">
        <Table filters={<MonthlyAdtFilters activeTab={tab} />} title={`Monthly ${label.toLowerCase()}`}
          subtitle={`Monthly totals for the selected locations and payers.${filterNote}`}
          columns={tableColumns} rows={rows} getRowKey={row => row.date} {...status}
          initialSort={{ columnId: 'date', direction: 'ascending' }} internalScroll stickyFirstColumn
          emptyMessage="No months match the selected range."
          csvFileName={`monthly-${tab}-${start.format('YYYY-MM')}-to-${end.format('YYYY-MM')}.csv`} />
      </div>
    </FullScreenModal>
  </>
}
