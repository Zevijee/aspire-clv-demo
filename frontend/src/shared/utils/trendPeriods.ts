export function trendBlockSize(startDate: string, endDate: string) {
  const days = Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86400000) + 1
  const minimum = Math.max(1, Math.ceil(days / 60))
  for (let size = minimum; size <= Math.floor(days / 15); size++) {
    if (days % size === 0) return size
  }
  return minimum
}

export function groupTrendPeriods<T extends { date: string; value: number }>(
  items: T[], startDate: string, blockSize: number, merge?: (first: T, next: T) => T,
): (T & { end_date: string })[] {
  const groups = new Map<number, T & { end_date: string }>()
  for (const item of [...items].sort((a, b) => a.date.localeCompare(b.date))) {
    const offset = Math.round((Date.parse(item.date) - Date.parse(startDate)) / 86400000)
    const key = Math.floor(offset / blockSize)
    const first = groups.get(key)
    groups.set(key, first ? { ...(merge ? merge(first, item) : first),
      date: first.date, value: first.value + item.value, end_date: item.date }
      : { ...item, end_date: item.date })
  }
  return [...groups.values()]
}
