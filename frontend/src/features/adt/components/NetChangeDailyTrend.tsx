import { useState } from 'react'
import { NetChangePayerFilter } from './NetChangePayerFilter'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { trendBlockSize, groupTrendPeriods } from '../../../shared/utils/trendPeriods'
import { DailyChangeChart } from '../../../shared/components/charts/DailyChangeChart'
import { NetChangeDayOverDay, type DailyMovement } from './NetChangeDayOverDay'
import type { NetChangeMetrics } from '../api/netChangeOverview'

export function NetChangeDailyTrend({ daily, startDate, endDate, hasPayers,
    loading, error, onRetry }: {
  daily: (NetChangeMetrics & { date: string })[]
  startDate: string
  endDate: string
  hasPayers: boolean
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}) {
  const [showTable, setShowTable] = useState(false)
  const rows: DailyMovement[] = daily.map(row => ({
    date: row.date, value: row.net_change,
    opening_census: row.opening_census, closing_census: row.closing_census,
    admissions: row.admissions, discharges: row.discharges,
    payer_changes_in: row.payer_changes_in, payer_changes_out: row.payer_changes_out,
  }))
  const days = Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86400000) + 1
  const blockSize = trendBlockSize(startDate, endDate)
  // Grouping keeps the first block's opening and the last block's closing, so a
  // multi-day bar still reads as one period rather than a sum of censuses.
  const items = groupTrendPeriods(rows, startDate, blockSize,
    (first, next) => ({ ...first, closing_census: next.closing_census }))
  const remainder = days % blockSize
  return <>
    <DailyChangeChart items={items} interval="day" loading={loading} error={error} onRetry={onRetry}
      headerActions={<OpenViewButton kind="table" label="See in table format" onClick={() => setShowTable(true)} />}
      title="Net change trend"
      subtitle={blockSize === 1 ? 'Close census compared with open census each day'
        : `Each bar shows ${blockSize} days of net change, starting from the selected start date.${remainder ? ` The final bar covers ${remainder} ${remainder === 1 ? 'day' : 'days'}.` : ''}`} />
    <FullScreenModal open={showTable} onClose={() => setShowTable(false)} destroyOnHidden
      title={`Net change by day: ${startDate} to ${endDate}`}>
      <div className="net-change-daily-modal__table">
        <NetChangeDayOverDay filters={<NetChangePayerFilter />} rows={rows} hasPayers={hasPayers} startDate={startDate}
          endDate={endDate} loading={loading} error={error} onRetry={onRetry} />
      </div>
    </FullScreenModal>
  </>
}
