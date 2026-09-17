import { DatePicker } from 'antd'
import dayjs from 'dayjs'

type DateRangePickerProps = {
  endDate: string
  onDateRangeChange: (startDate: string, endDate: string) => void
  startDate: string
}

export function DateRangePicker({ endDate, onDateRangeChange, startDate }: DateRangePickerProps) {
  return (
    <div className="date-range-picker">
      <span>Date range</span>
      <DatePicker.RangePicker
        allowClear={false}
        aria-label="Admission date range"
        disabledDate={(current) => current.isAfter(dayjs(), 'day')}
        format="MM/DD/YYYY"
        value={[dayjs(startDate), dayjs(endDate)]}
        onChange={(dates) => {
          if (dates === null || dates[0] === null || dates[1] === null) {
            return
          }

          onDateRangeChange(dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD'))
        }}
      />
    </div>
  )
}
