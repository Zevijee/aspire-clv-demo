import { Table, type TableColumn } from '../../../shared/components/Table'
import type { useNetChangeDaily, DailyMovement } from '../hooks/useNetChangeDaily'

const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})

export function NetChangeDayOverDay({ daily }: { daily: ReturnType<typeof useNetChangeDaily> }) {
  const metrics: { id: 'opening_census' | 'admissions' | 'discharges' | 'closing_census' | 'payer_changes_in' | 'payer_changes_out'; header: string }[] = [
    { id: 'opening_census', header: 'Open census' },
    { id: 'admissions', header: 'Admissions' },
    { id: 'discharges', header: 'Discharges' },
    { id: 'closing_census', header: 'Close census' },
    ...(daily.hasPayers ? [
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
      value: row => row[id] ?? '—',
      format: value => typeof value === 'number' ? value.toLocaleString() : value,
    })),
  ]
  return <Table title="Day over day"
    subtitle="Daily census and resident movement for the selected locations and payers."
    columns={columns} rows={daily.items} getRowKey={row => row.date}
    loading={daily.loading} error={daily.error} onRetry={daily.onRetry}
    initialSort={{ columnId: 'date', direction: 'ascending' }}
    internalScroll stickyFirstColumn
    csvFileName={`net-change-day-over-day-${daily.startDate}-to-${daily.endDate}.csv`}
    emptyMessage="No days match the selected range." />
}
