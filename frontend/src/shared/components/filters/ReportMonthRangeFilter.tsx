import { DatePicker } from 'antd'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'

/** The month range in the URL, or by default the last 24 complete months,
 * ending last month: the month in progress is left out, since its partial days
 * would read as a dip. It can still be chosen in the picker. */
export function getReportMonthRange(params: URLSearchParams) {
  const end = params.has('end_month') ? dayjs(params.get('end_month')).startOf('month')
    : dayjs().startOf('month').subtract(1, 'month')
  const start = params.has('start_month') ? dayjs(params.get('start_month')).startOf('month') : end.subtract(23, 'month')
  return { start, end }
}

export function ReportMonthRangeFilter() {
  const [params, setParams] = useSearchParams()
  const { start, end } = getReportMonthRange(params)
  return <div className="date-range-picker">
    <span>Month range</span>
    <DatePicker.RangePicker picker="month" format="MMM YYYY" allowClear={false}
      aria-label="Report month range" value={[start, end]}
      disabledDate={current => current.isAfter(dayjs(), 'month')}
      onChange={dates => {
        if (!dates?.[0] || !dates[1]) return
        const next = new URLSearchParams(params)
        next.set('start_month', dates[0].format('YYYY-MM'))
        next.set('end_month', dates[1].format('YYYY-MM'))
        setParams(next)
      }} />
  </div>
}
