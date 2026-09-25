import type { ReactNode } from 'react'
import { FullScreenModal } from './FullScreenModal'
import { Table, type TableColumn } from './Table'
import { LocationName } from './LocationName'

type AllFacilitiesModalProps<Row> = {
  open: boolean
  onClose: () => void
  title: string
  subtitle: string
  rows: Row[]
  /** The report's own measure columns, the same ones its drilldown shows. */
  columns: TableColumn<Row>[]
  getRowKey: (row: Row) => string
  getName: (row: Row) => string
  /** State, portfolio and region, in that order. */
  getPath: (row: Row) => readonly [string, string, string]
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  csvFileName: string
  /** The report's own filters, repeated here because the modal covers them. */
  filters?: ReactNode
}

/** Every facility at once, whatever level a drilldown is showing: one row per
 * facility, with the hierarchy as header filters and no total row. Every
 * drilldown opens this from its Show all facilities button. */
export function AllFacilitiesModal<Row>({ open, onClose, title, subtitle, rows, columns, getRowKey,
  getName, getPath, loading, error, onRetry, csvFileName, filters }: AllFacilitiesModalProps<Row>) {
  const tableColumns: TableColumn<Row>[] = [
    { id: 'facility', header: 'Facility', isRowHeader: true, value: getName,
      format: (_, row) => { const [state, portfolio, region] = getPath(row)
        return <LocationName region={region} portfolio={portfolio} state={state}>{getName(row)}</LocationName> } },
    // Filters in the header rather than columns; the name shows them on hover.
    ...(['State', 'Portfolio', 'Region'] as const).map((header, index): TableColumn<Row> => ({
      id: header.toLowerCase(), header, filterable: true, hidden: true, value: row => getPath(row)[index] })),
    ...columns,
  ]
  return <FullScreenModal open={open} onClose={onClose} destroyOnHidden title={title}>
    <div className="net-change-daily-modal__table">
      <Table<Row> title="Facilities" subtitle={subtitle} columns={tableColumns} rows={rows}
        getRowKey={getRowKey} initialSort={{ columnId: 'facility', direction: 'ascending' }}
        internalScroll searchable stickyFirstColumn filters={filters}
        loading={loading} error={error} onRetry={onRetry}
        emptyMessage="No facilities match these filters." csvFileName={csvFileName} />
    </div>
  </FullScreenModal>
}
