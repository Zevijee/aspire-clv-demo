import { DatePicker } from 'antd'
import dayjs from 'dayjs'
import { useReportSearchParams } from '../ReportSearchContext'

/** A single-day picker for reports that show one day, such as Daily Census.
 * Defaults to today; future days cannot be chosen. Picking today removes the
 * parameter, so the link does not freeze on the day it was made. */
export function ReportDateFilter({ param = 'date', label = 'Date', earliest }: {
  param?: string
  label?: string
  /** The first day that can be chosen, YYYY-MM-DD. */
  earliest?: string
}) {
  const [params, setParams] = useReportSearchParams()
  // Absent means today, so a bookmarked link keeps following the current day.
  const value = params.get(param) ?? dayjs().format('YYYY-MM-DD')
  return <div className="date-range-picker date-range-picker--single">
    <span>{label}</span>
    <DatePicker allowClear={false} format="MM/DD/YYYY" aria-label={label} value={dayjs(value)}
      disabledDate={current => current.isAfter(dayjs(), 'day')
        || (earliest !== undefined && current.isBefore(dayjs(earliest), 'day'))}
      onChange={day => {
        if (!day) return
        const next = new URLSearchParams(params)
        if (day.isSame(dayjs(), 'day')) next.delete(param)
        else next.set(param, day.format('YYYY-MM-DD'))
        setParams(next)
      }} />
  </div>
}
