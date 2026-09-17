import { Table, type TableProps } from './Table'

/** Drill-down tables include totals for multiple visible rows automatically.
 * Supply getFooterRow for distinct counts, weighted averages, or other custom totals.
 */
export function DrilldownTable<Row>({ getFooterRow, columns, ...props }: TableProps<Row>) {
  const totalRow = {} as Row
  let totals = new Map<string, number | string>()
  return <Table<Row> {...props} stickyFirstColumn={props.stickyFirstColumn ?? true}
    stickyFooterRow={props.stickyFooterRow ?? true}
    columns={getFooterRow ? columns : columns.map(column => ({
      ...column,
      value: row => row === totalRow ? totals.get(column.id) ?? '' : column.value(row),
      format: (value, row) => row === totalRow
        ? typeof value === 'number' ? value.toLocaleString() : value
        : column.format ? column.format(value, row) : column.change && typeof value === 'number'
          ? value.toLocaleString(undefined, { signDisplay: 'exceptZero' }) : value,
    }))}
    getFooterRow={rows => {
      if (rows.length <= 1) return null
      if (getFooterRow) return getFooterRow(rows)
      totals = new Map(columns.map((column, index) => [column.id,
        index === 0 ? 'Total' : column.numeric
          ? rows.reduce((sum, row) => {
            const value = column.value(row)
            return sum + (typeof value === 'number' && Number.isFinite(value) ? value : 0)
          }, 0) : '',
      ]))
      return totalRow
    }} />
}
