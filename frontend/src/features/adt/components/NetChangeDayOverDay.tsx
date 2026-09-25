import type { ReactNode } from 'react'
import { Table, type TableColumn } from '../../../shared/components/Table'
import type { DailyChangeItem } from '../../../shared/components/charts/DailyChangeChart'

export type DailyMovement = DailyChangeItem & {
  admissions: number; discharges: number
  payer_changes_in: number; payer_changes_out: number
}

const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})

export function NetChangeDayOverDay({ rows, hasPayers, startDate, endDate,
    loading, error, onRetry, filters }: {
  /** The report's payer filter, shown here because this table opens in a modal. */
  filters?: ReactNode
  rows: DailyMovement[]
  hasPayers: boolean
  startDate: string
  endDate: string
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}) {
  const metrics: { id: keyof DailyMovement; header: string }[] = [
    { id: 'opening_census', header: 'Open census' },
    { id: 'admissions', header: 'Admissions' },
    { id: 'discharges', header: 'Discharges' },
    { id: 'closing_census', header: 'Close census' },
    ...(hasPayers ? [
      { id: 'payer_changes_in' as const, header: 'Payer in' },
      { id: 'payer_changes_out' as const, header: 'Payer out' },
    ] : []),
  ]
  const columns: TableColumn<DailyMovement>[] = [
    { id: 'date', header: 'Date', isRowHeader: true, value: row => row.date,
      format: (_, row) => dateFormat.format(new Date(`${row.date}T00:00:00Z`)) },
    { id: 'value', header: 'Net change', numeric: true, value: row => row.value,
      change: { favorable: 'increase' } },
    ...metrics.map(({ id, header }): TableColumn<DailyMovement> => ({ id, header, numeric: true,
      value: row => (row[id] ?? '—') as string | number,
      format: value => typeof value === 'number' ? value.toLocaleString() : value,
    })),
  ]
  return <Table filters={filters} title="Day over day"
    subtitle="Daily census and resident movement for the selected locations and payers."
    columns={columns} rows={rows} getRowKey={row => row.date}
    loading={loading} error={error} onRetry={onRetry}
    initialSort={{ columnId: 'date', direction: 'ascending' }}
    internalScroll stickyFirstColumn
    csvFileName={`net-change-day-over-day-${startDate}-to-${endDate}.csv`}
    emptyMessage="No days match the selected range." />
}
