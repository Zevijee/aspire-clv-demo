import dayjs from 'dayjs'

function formatDate(date: Date): string {
  // Report boundaries are local calendar dates, not UTC timestamps.
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function getDefaultReportDateRange(now = new Date()): { endDate: string; startDate: string } {
  const endDate = new Date(now)
  const startDate = new Date(endDate)
  startDate.setDate(endDate.getDate() - 29)

  return {
    endDate: formatDate(endDate),
    startDate: formatDate(startDate),
  }
}

export function formatReportDateRange(startDate: string, endDate: string): string {
  const start = dayjs(startDate)
  const end = dayjs(endDate)
  const dayCount = end.diff(start, 'day') + 1

  return `${start.format('dddd, MMMM D, YYYY')} to ${end.format(
    'dddd, MMMM D, YYYY',
  )} (${dayCount} ${dayCount === 1 ? 'day' : 'days'})`
}
