import { useSearchParams } from 'react-router-dom'

import { getDefaultReportDateRange } from '../../utils/reportDateRange'
import { DateRangePicker } from './DateRangePicker'

export function ReportDateRangeFilter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate

  return (
    <DateRangePicker
      endDate={endDate}
      startDate={startDate}
      onDateRangeChange={(nextStartDate, nextEndDate) => {
        const nextSearchParams = new URLSearchParams(searchParams)

        nextSearchParams.set('end_date', nextEndDate)
        nextSearchParams.set('start_date', nextStartDate)
        setSearchParams(nextSearchParams)
      }}
    />
  )
}
