import { trendBlockSize, groupTrendPeriods } from '../../../shared/utils/trendPeriods'
import { DailyChangeChart } from '../../../shared/components/charts/DailyChangeChart'
import { useNetChangeDaily } from '../hooks/useNetChangeDaily'
import { useState } from 'react'
import { Modal } from 'antd'
import { NetChangeDayOverDay } from './NetChangeDayOverDay'

export function NetChangeDailyTrend() {
  const [showTable, setShowTable] = useState(false)
  const daily = useNetChangeDaily()
  const days = Math.round((Date.parse(daily.endDate) - Date.parse(daily.startDate)) / 86400000) + 1
  const blockSize = trendBlockSize(daily.startDate, daily.endDate)
  const items = groupTrendPeriods(daily.items, daily.startDate, blockSize,
    (first, next) => ({ ...first, closing_census: next.closing_census }))
  const remainder = days % blockSize
  return <><DailyChangeChart {...daily} items={items} interval="day"
    headerActions={<button type="button" className="report-table__export" onClick={() => setShowTable(true)}>
      See in table format
    </button>}
    title="Net change trend"
    subtitle={blockSize === 1 ? 'Close census compared with open census each day'
      : `Each bar shows ${blockSize} days of net change, starting from the selected start date.${remainder ? ` The final bar covers ${remainder} ${remainder === 1 ? 'day' : 'days'}.` : ''}`} />
    <Modal open={showTable} onCancel={() => setShowTable(false)} footer={null}
      title={`Net change by day: ${daily.startDate} to ${daily.endDate}`}
      width="calc(100vw - 48px)" className="net-change-daily-modal" style={{ top: 24, paddingBottom: 0, maxWidth: 'calc(100vw - 48px)' }} destroyOnHidden>
      <div className="net-change-daily-modal__table"><NetChangeDayOverDay daily={daily} /></div>
    </Modal>
  </>
}
