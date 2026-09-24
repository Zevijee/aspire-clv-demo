export type TableFilterSource = {
  endpoint?: string
  id: 'admissions' | 'discharges' | 'payer-changes' | 'net-change-logs' | 'census-residents'
  startDate: string
  endDate: string
}

type FilterColumn<Row> = {
  id: string
  value: (row: Row) => string | number
  format?: (value: string | number, row: Row) => unknown
}

export function matchesTableSearch<Row>(row: Row, columns: FilterColumn<Row>[], search: string) {
  const term = search.trim().toLowerCase()
  return !term || columns.some((column) => {
    const value = column.value(row)
    return [value, column.format?.(value, row)].some((candidate) =>
      (typeof candidate === 'string' || typeof candidate === 'number') &&
      String(candidate).toLowerCase().includes(term))
  })
}

export function matchesTableFilters<Row>(row: Row, columns: FilterColumn<Row>[],
  filters: Record<string, string[]>, excludedColumn?: string) {
  return columns.every((column) => column.id === excludedColumn ||
    !filters[column.id]?.length || filters[column.id].includes(String(column.value(row))))
}

export function otherTableFilters(filters: Record<string, string[]>, columnId: string) {
  return Object.fromEntries(Object.entries(filters)
    .filter(([key, values]) => key !== columnId && values.length > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, values]) => [key, [...new Set(values)].sort()]))
}

export function tableFilterRequestKey(source: TableFilterSource, column: string,
  filters: Record<string, string[]>, search: string) {
  return JSON.stringify([source.id, source.startDate, source.endDate, column,
    otherTableFilters(filters, column), search.trim(), source.endpoint])
}
