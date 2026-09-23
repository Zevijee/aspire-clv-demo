import dayjs from 'dayjs'
import { useState } from 'react'
import { Modal } from 'antd'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useSearchParams } from 'react-router-dom'
import { getReportMonthRange } from '../../../shared/components/filters/ReportMonthRangeFilter'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { DailyChangeChart } from '../../../shared/components/charts/DailyChangeChart'
import { useMonthlyAdt, type MonthlyMovement } from '../hooks/useMonthlyAdt'
import { monthlyFilter, type MonthlyTab } from '../api/monthlyAdt'
import { MonthlyAdtLocations } from './MonthlyAdtLocations'
import { AdmissionsOverviewModal, type AdmissionsMonthSelection } from './AdmissionsOverviewModal'

export function MonthlyAdtTrending({ activeTab }: { activeTab: string }) {
  const [admissionsMonth, setAdmissionsMonth] = useState<AdmissionsMonthSelection | null>(null)
  const [showTable, setShowTable] = useState(false)
  const [path, setPath] = useState<string[]>([])
  const [params] = useSearchParams()
  const { start, end } = getReportMonthRange(params)
  const lastDay = end.isSame(dayjs(), 'month') ? dayjs() : end.endOf('month')
  const tab = (['admissions', 'discharges', 'net-change'].includes(activeTab)
    ? activeTab : 'admissions') as MonthlyTab
  const filter = monthlyFilter[tab as keyof typeof monthlyFilter]
  const filterValues = filter ? params.getAll(filter.search) : []
  // The API groups by month from each view's own monthly rollup, so nothing is
  // bucketed here.
  const daily = useMonthlyAdt({ startDate: start.format('YYYY-MM-DD'), endDate: lastDay.format('YYYY-MM-DD'),
    payers: params.getAll('monthly_payer'), path, tab, filterValues })
  const rows: MonthlyMovement[] = daily.months
  const tableLabel = activeTab === 'net-change' ? 'Net change' : activeTab === 'discharges' ? 'Discharges' : 'Admissions'
  const columns: TableColumn<(typeof rows)[number]>[] = [
    { id: 'date', header: 'Month', isRowHeader: true, value: row => row.date,
      format: (_, row) => dayjs(row.date).format('MMM YYYY') },
    { id: 'value', header: 'Net change', numeric: true, value: row => row.value, change: { favorable: 'increase' } },
    ...(['opening_census', 'admissions', 'discharges', 'closing_census'] as const).map(id => ({
      id, header: { opening_census: 'Open census', admissions: 'Admissions', discharges: 'Discharges', closing_census: 'Close census' }[id],
      numeric: true, value: (row: (typeof rows)[number]) => row[id],
    })),
    ...(daily.hasPayers ? (['payer_changes_in', 'payer_changes_out'] as const).map(id => ({
      id, header: id === 'payer_changes_in' ? 'Payer in' : 'Payer out', numeric: true,
      value: (row: (typeof rows)[number]) => row[id],
    })) : []),
  ]
  const tableColumns: TableColumn<(typeof rows)[number]>[] = activeTab === 'net-change' ? columns : [columns[0],
    { id: activeTab, header: tableLabel, numeric: true,
      value: (row: (typeof rows)[number]) => activeTab === 'discharges' ? row.discharges : row.admissions },
    { id: 'average', header: 'Average per day', numeric: true,
      value: (row: (typeof rows)[number]) => (activeTab === 'discharges' ? row.discharges : row.admissions)
        / (dayjs(row.end_date).diff(dayjs(row.date), 'day') + 1),
      format: (value: string | number) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) },
  ]
  const dailyMetric = activeTab === 'net-change' ? 'value' : activeTab === 'discharges' ? 'discharges' : 'admissions'
  for (const high of [true, false]) {
    const extreme = (row: (typeof rows)[number]) => row.days.length
      ? (high ? Math.max : Math.min)(...row.days.map(day => day[dailyMetric])) : 0
    tableColumns.push({
      id: high ? 'highest_day' : 'lowest_day', header: high ? 'Highest day' : 'Lowest day', numeric: true,
      value: extreme,
      change: activeTab === 'net-change' ? { favorable: 'increase' } : undefined,
      format: (_, row) => {
        if (!row.days.length) return '—'
        const value = extreme(row)
        const dates = row.days.filter(day => day[dailyMetric] === value).map(day => dayjs(day.date).format('MMM D, YYYY'))
        return <span title={dates.join(', ')}>{value.toLocaleString(undefined, { signDisplay: activeTab === 'net-change' ? 'exceptZero' : 'auto' })}
          {' '}<small>({dates[0]}{dates.length > 1 ? ` +${dates.length - 1}` : ''})</small></span>
      },
    })
  }
  return <>
    <AdmissionsOverviewModal month={admissionsMonth} onClose={() => setAdmissionsMonth(null)} />
    <MonthlyAdtLocations activeTab={activeTab} startDate={start.format('YYYY-MM-DD')} endDate={lastDay.format('YYYY-MM-DD')}
      path={path} setPath={setPath} />
    {activeTab === 'net-change' && <DailyChangeChart title="Monthly net change"
      onSelect={item => setAdmissionsMonth({ start: item.date, end: item.end_date ?? item.date, path, payers: params.getAll('monthly_payer'), report: 'net-change' })}
      headerActions={<button type="button" className="report-table__export" onClick={() => setShowTable(true)}>See in table view</button>}
      subtitle={`Close census compared with open census each month.${end.isSame(dayjs(), 'month') ? ' Current month is month to date.' : ''}`}
      items={rows} interval="month" height={400}
      loading={daily.loading} error={daily.error} onRetry={daily.onRetry} />}
    {([
    { key: 'admissions', title: 'Monthly admissions', label: 'Admissions', signed: false, color: 'var(--color-table-change-favorable)' },
    { key: 'discharges', title: 'Monthly discharges', label: 'Discharges', signed: false, color: 'var(--color-table-change-adverse)' },
  ] as const).filter(metric => metric.key === activeTab).map(metric => <LineChart key={metric.key} title={metric.title}
    onSelect={item => setAdmissionsMonth({ start: item.date, end: item.end_date ?? item.date, path, payers: params.getAll('monthly_payer'), report: metric.key })}
    headerActions={<button type="button" className="report-table__export" onClick={() => setShowTable(true)}>See in table view</button>}
    subtitle={`Total ${metric.label.toLowerCase()} per calendar month.${filterValues.length ? ` ${filter.label} ${filterValues.join(', ')}.` : ''}${end.isSame(dayjs(), 'month') ? ' Current month is month to date.' : ''}${metric.key === 'admissions' ? ' Click a month to open Admissions Overview.' : ''}`}
    items={rows.map(row => ({ date: row.date, end_date: row.end_date, value: row[metric.key] }))}
    variant="bar" interval="month" height={400} signed={metric.signed} barColor={metric.color} showDailyAverage
    valueLabel={metric.label} loading={daily.loading} error={daily.error} onRetry={daily.onRetry} />)}
    <Modal open={showTable} onCancel={() => setShowTable(false)} footer={null}
      title={`Monthly ${tableLabel.toLowerCase()}: ${start.format('MMM YYYY')} to ${end.format('MMM YYYY')}`}
      width="calc(100vw - 48px)" className="net-change-daily-modal"
      style={{ top: 24, paddingBottom: 0, maxWidth: 'calc(100vw - 48px)' }} destroyOnHidden>
      <div className="net-change-daily-modal__table">
        <Table key={activeTab} title={`Monthly ${tableLabel.toLowerCase()}`}
          subtitle={`Monthly totals for the selected locations and payers.${filterValues.length ? ` ${filter.label} ${filterValues.join(', ')}.` : ''}`}
          columns={tableColumns} rows={rows} getRowKey={row => row.date}
          loading={daily.loading} error={daily.error} onRetry={daily.onRetry}
          initialSort={{ columnId: 'date', direction: 'ascending' }} internalScroll stickyFirstColumn
          emptyMessage="No months match the selected range."
          csvFileName={`monthly-${activeTab}-${start.format('YYYY-MM')}-to-${end.format('YYYY-MM')}.csv`} />
      </div>
    </Modal>
  </>
}
