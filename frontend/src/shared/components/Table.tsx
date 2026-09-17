import { createPortal } from 'react-dom'
import { BooleanBadge } from './BooleanBadge'
import { DataState, type DataStateProps } from './DataState'
import { useEffect, useLayoutEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { MultiSelectFilterOptions } from './filters/MultiSelectFilterOptions'
import { useTableFilterOptions } from '../hooks/useTableFilterOptions'
import { matchesTableFilters, matchesTableSearch, type TableFilterSource } from '../utils/tableFilters'
import { tableChange, type FavorableChange } from '../utils/tableChange'

type SortDirection = 'ascending' | 'descending'
type SortValue = number | string
type NumericFilterOperator = 'between' | 'equal' | 'greater-than' | 'less-than'

type NumericFilter = {
  operator: NumericFilterOperator
  primaryValue: string
  secondaryValue: string
}

export type TableColumn<Row> = {
  /** Shared signed comparison formatting and colors, including total rows. */
  change?: { favorable: FavorableChange; value?: (row: Row) => number | null }
  /** Render Yes/No values using the shared boolean badge. */
  dataType?: 'boolean'
  negativeWhenTrue?: boolean
  highlightOnHover?: boolean
  filterable?: boolean
  format?: (value: SortValue, row: Row) => ReactNode
  /** Optional CSV text when the displayed value includes meaningful status. */
  exportValue?: (row: Row) => SortValue
  header: string
  id: string
  initialSortDirection?: SortDirection
  isRowHeader?: boolean
  numeric?: boolean
  sortable?: boolean
  value: (row: Row) => SortValue
  sortValue?: (row: Row) => SortValue
}

function renderTableCell<Row>(column: TableColumn<Row>, row: Row) {
  const value = column.value(row)
  if (column.dataType === 'boolean') {
    return <BooleanBadge negativeWhenTrue={column.negativeWhenTrue}
      value={value === 'Yes' ? true : value === 'No' ? false : null} />
  }
  if (column.change) {
    const change = tableChange(column.change.value ? column.change.value(row) : value, column.change.favorable)
    return <span className={change.className}>
      {column.format ? column.format(value, row) : change.text}
    </span>
  }
  return column.format ? column.format(value, row) : value
}

export type TableProps<Row> = DataStateProps & {
  retainRowsWhileLoading?: boolean
  columns: TableColumn<Row>[]
  stickyFirstColumn?: boolean
  stickyFooterRow?: boolean
  highlightColumnOnHover?: boolean
  initialSort?: SortState
  initialFilters?: Record<string, string[]>
  clearableFilters?: boolean
  headerActions?: ReactNode
  onClearFilters?: () => void
  csvFileName?: string
  showExport?: boolean
  showRowCount?: boolean
  getExportRows?: () => Promise<Row[]>
  emptyMessage: string
  footer?: ReactNode
  getFooterRow?: (visibleRows: Row[]) => Row | null
  getRowKey: (row: Row) => string
  getRowClassName?: (row: Row) => string | undefined
  onRowClick?: (row: Row) => void
  internalScroll?: boolean
  onQueryChange?: (query: TableQuery) => void
  rows: Row[]
  searchable?: boolean
  /** Total matching rows across all pages for server-side tables. */
  totalRows?: number
  subtitle: string
  title: string
} & (
  | { serverSide: true; filterSource: TableFilterSource }
  | { serverSide?: false; filterSource?: never }
)

type SortState = {
  columnId: string
  direction: SortDirection
}

export type TableQuery = {
  filters: Record<string, string[]>
  search?: string
  sort: SortState | null
}

const textCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })
const numericFilterOperators: NumericFilterOperator[] = [
  'equal',
  'greater-than',
  'less-than',
  'between',
]

function getNumericFilterOperator(value: string): NumericFilterOperator {
  return numericFilterOperators.find((operator) => operator === value) ?? 'equal'
}

function matchesNumericFilter(value: number, filter: NumericFilter | undefined) {
  if (filter === undefined || filter.primaryValue.trim() === '') {
    return true
  }

  const primaryValue = Number(filter.primaryValue)
  if (!Number.isFinite(primaryValue)) {
    return true
  }

  if (filter.operator === 'equal') {
    return value === primaryValue
  }

  if (filter.operator === 'greater-than') {
    return value > primaryValue
  }

  if (filter.operator === 'less-than') {
    return value < primaryValue
  }

  if (filter.secondaryValue.trim() === '') {
    return true
  }

  const secondaryValue = Number(filter.secondaryValue)
  if (!Number.isFinite(secondaryValue)) {
    return true
  }

  return value >= Math.min(primaryValue, secondaryValue) && value <= Math.max(primaryValue, secondaryValue)
}

function hasNumericFilter(filter: NumericFilter | undefined) {
  if (filter === undefined || filter.primaryValue.trim() === '') {
    return false
  }

  return filter.operator !== 'between' || filter.secondaryValue.trim() !== ''
}

type NumericFilterControlsProps = {
  filter?: NumericFilter
  message?: string
  onApply: (filter: NumericFilter) => void
  onClear: () => void
}

function NumericFilterControls({ filter, message, onApply, onClear }: NumericFilterControlsProps) {
  const [draftFilter, setDraftFilter] = useState<NumericFilter>(
    filter ?? {
      operator: 'equal',
      primaryValue: '',
      secondaryValue: '',
    },
  )

  return (
    <div className="report-table__numeric-filter">
      <label>
        <span>Condition</span>
        <select
          onChange={(event) => {
            setDraftFilter((currentFilter) => ({
              ...currentFilter,
              operator: getNumericFilterOperator(event.target.value),
            }))
          }}
          value={draftFilter.operator}
        >
          <option value="equal">Equal to</option>
          <option value="greater-than">More than</option>
          <option value="less-than">Less than</option>
          <option value="between">Between</option>
        </select>
      </label>
      <label>
        <span>{draftFilter.operator === 'between' ? 'From' : 'Value'}</span>
        <input
          autoFocus
          onChange={(event) => {
            setDraftFilter((currentFilter) => ({
              ...currentFilter,
              primaryValue: event.target.value,
            }))
          }}
          step="any"
          type="number"
          value={draftFilter.primaryValue}
        />
      </label>
      {draftFilter.operator === 'between' && (
        <label>
          <span>To</span>
          <input
            onChange={(event) => {
              setDraftFilter((currentFilter) => ({
                ...currentFilter,
                secondaryValue: event.target.value,
              }))
            }}
            step="any"
            type="number"
            value={draftFilter.secondaryValue}
          />
        </label>
      )}
      <div className="report-table__numeric-filter-actions">
        <button
          className="report-table__filter-action report-table__filter-action--clear"
          onClick={() => {
            setDraftFilter({
              operator: 'equal',
              primaryValue: '',
              secondaryValue: '',
            })
            onClear()
          }}
          type="button"
        >
          Clear
        </button>
        <button
          className="report-table__filter-action"
          onClick={() => onApply(draftFilter)}
          type="button"
        >
          Apply
        </button>
      </div>
      {message !== undefined && <p className="report-table__numeric-filter-message">{message}</p>}
    </div>
  )
}

function DownloadIcon() {
  return (
    <svg aria-hidden="true" className="report-table__export-icon" fill="none" viewBox="0 0 24 24">
      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" />
    </svg>
  )
}

function FilterIcon() {
  return (
    <svg aria-hidden="true" className="report-table__filter-icon" fill="none" viewBox="0 0 24 24">
      <path d="M4 5h16l-6 7v5l-4 2v-7z" />
    </svg>
  )
}

function SortIcon({ direction }: { direction?: SortDirection }) {
  if (direction === 'ascending') {
    return (
      <svg aria-hidden="true" className="report-table__sort-icon" fill="none" viewBox="0 0 24 24">
        <path d="m8 11 4-4 4 4M12 7v14" />
      </svg>
    )
  }

  if (direction === 'descending') {
    return (
      <svg aria-hidden="true" className="report-table__sort-icon" fill="none" viewBox="0 0 24 24">
        <path d="m8 13 4 4 4-4M12 17V3" />
      </svg>
    )
  }

  return (
    <svg aria-hidden="true" className="report-table__sort-icon" fill="none" viewBox="0 0 24 24">
      <path d="m8 7 4-4 4 4M16 17l-4 4-4-4" />
    </svg>
  )
}

function escapeCsvValue(value: SortValue) {
  return `"${String(value).replace(/"/g, '""')}"`
}

export function downloadCsv<Row>(fileName: string, columns: TableColumn<Row>[], rows: Row[]) {
  const csv = [
    columns.map((column) => escapeCsvValue(column.header)),
    ...rows.map((row) => columns.map((column) => escapeCsvValue(
      column.exportValue ? column.exportValue(row) : column.value(row),
    ))),
  ]
    .map((row) => row.join(','))
    .join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const downloadUrl = URL.createObjectURL(blob)
  const downloadLink = document.createElement('a')

  downloadLink.download = fileName
  downloadLink.href = downloadUrl
  document.body.append(downloadLink)
  downloadLink.click()
  downloadLink.remove()
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0)
}

export function Table<Row>({
  loading,
  retainRowsWhileLoading = false,
  error,
  onRetry,
  columns,
  stickyFirstColumn = false,
  stickyFooterRow = false,
  highlightColumnOnHover = false,
  initialSort,
  initialFilters,
  clearableFilters = false,
  headerActions,
  onClearFilters,
  csvFileName,
  showExport = true,
  showRowCount = true,
  getExportRows,
  emptyMessage,
  filterSource,
  footer,
  getFooterRow,
  getRowKey,
  getRowClassName,
  onRowClick,
  internalScroll = false,
  onQueryChange,
  rows,
  searchable = false,
  serverSide = false,
  totalRows,
  title,
}: TableProps<Row>) {
  const [hoveredColumn, setHoveredColumn] = useState<string | null>(null)
  function highlightColumn(cell: HTMLTableCellElement, columnId: string) {
    const table = cell.closest('table')
    if (!table) return
    let contentWidth = 0
    for (const row of Array.from(table.rows)) {
      const columnCell = row.cells[cell.cellIndex]
      if (!columnCell || columnCell.colSpan !== 1) continue
      const content = columnCell.querySelector('.report-table__column-header') ?? columnCell
      const range = document.createRange()
      range.selectNodeContents(content)
      contentWidth = Math.max(contentWidth, range.getBoundingClientRect().width)
    }
    const padding = getComputedStyle(cell).getPropertyValue('--space-4')
    table.style.setProperty('--table-column-highlight-width', `calc(${Math.ceil(contentWidth)}px + ${padding} + ${padding})`)
    setHoveredColumn(columnId)
  }
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const titleId = useId()
  const activeFilterMenuRef = useRef<HTMLDivElement | null>(null)
  const filterPopupRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const horizontalScrollRef = useRef<HTMLDivElement | null>(null)
  const [horizontalTrack, setHorizontalTrack] = useState({ left: 0, width: 0, content: 0 })
  useLayoutEffect(() => {
    if (!stickyFirstColumn) return
    const scroller = scrollRef.current
    const table = scroller?.querySelector('table')
    const firstCell = table?.querySelector('thead th')
    const bar = horizontalScrollRef.current
    if (!scroller || !table || !firstCell || !bar) return
    const measure = () => {
      const left = Math.min(firstCell.getBoundingClientRect().width, scroller.clientWidth)
      const width = Math.max(0, scroller.clientWidth - left)
      const overflow = Math.max(0, scroller.scrollWidth - scroller.clientWidth)
      const next = { left, width, content: width + overflow }
      setHorizontalTrack((current) => current.left === next.left && current.width === next.width
        && current.content === next.content ? current : next)
    }
    const sync = () => { if (bar.scrollLeft !== scroller.scrollLeft) bar.scrollLeft = scroller.scrollLeft }
    const wheel = (event: WheelEvent) => {
      const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0)
      if (!delta || scroller.scrollWidth <= scroller.clientWidth) return
      event.preventDefault()
      scroller.scrollLeft += delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scroller.clientWidth : 1)
      sync()
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(scroller)
    observer.observe(table)
    observer.observe(firstCell)
    scroller.addEventListener('scroll', sync)
    scroller.addEventListener('wheel', wheel, { passive: false })
    return () => {
      observer.disconnect()
      scroller.removeEventListener('scroll', sync)
      scroller.removeEventListener('wheel', wheel)
    }
  }, [stickyFirstColumn, columns, rows, loading, error])
  useLayoutEffect(() => {
    if (horizontalScrollRef.current && scrollRef.current) {
      horizontalScrollRef.current.scrollLeft = scrollRef.current.scrollLeft
    }
  }, [horizontalTrack])
  const [lockedColumns, setLockedColumns] = useState<{ ids: string; widths: number[] } | null>(null)
  const columnIds = JSON.stringify(columns.map((column) => column.id))
  const lockedWidths = lockedColumns?.ids === columnIds ? lockedColumns.widths : null
  const queryScrollRef = useRef<{ left: number; rows: Row[]; visibleRows: Row[] } | null>(null)
  const [settledHeight, setSettledHeight] = useState(0)
  const [searchTerm, setSearchTerm] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const search = searchable ? (serverSide ? debouncedSearch : searchTerm.trim()) : ''
  const searchPending = searchable && serverSide && searchTerm.trim() !== debouncedSearch
  const [filterValues, setFilterValues] = useState<Record<string, string[]>>(() => initialFilters ?? {})
  const [numericFilterMessages, setNumericFilterMessages] = useState<
    Record<string, string | undefined>
  >({})
  const [numericFilterValues, setNumericFilterValues] = useState<Record<string, NumericFilter>>({})
  const [openFilterColumnId, setOpenFilterColumnId] = useState<string | null>(null)
  const [sortState, setSortState] = useState<SortState | null>(() => initialSort ?? null)
  const textFilterableColumns = useMemo(
    () => columns.filter((column) => column.filterable === true && column.numeric !== true),
    [columns],
  )
  const numericFilterableColumns = useMemo(
    () => columns.filter((column) => column.filterable === true && column.numeric === true),
    [columns],
  )
  const queryFilters = useMemo(() => serverSide ? {
    ...filterValues,
    ...Object.fromEntries(Object.entries(numericFilterValues)
      .filter(([, filter]) => hasNumericFilter(filter))
      .map(([key, filter]) => [key, [JSON.stringify([filter.operator, filter.primaryValue,
        ...(filter.operator === 'between' ? [filter.secondaryValue] : [])])]])),
  } : filterValues, [serverSide, filterValues, numericFilterValues])
  const remoteFilterOptions = useTableFilterOptions(
    serverSide ? filterSource : undefined,
    numericFilterableColumns.some((column) => column.id === openFilterColumnId) ? null : openFilterColumnId,
    queryFilters, search,
  )
  const filterOptions = useMemo(
    () =>
      new Map(
        textFilterableColumns.map((column) => {
          if (serverSide) {
            return [column.id, column.id === openFilterColumnId ? remoteFilterOptions.options : []]
          }

          const availableRows = rows.filter((row) =>
            matchesTableSearch(row, columns, search) &&
            matchesTableFilters(row, textFilterableColumns, filterValues, column.id) &&
            numericFilterableColumns.every((numericColumn) =>
              matchesNumericFilter(Number(numericColumn.value(row)), numericFilterValues[numericColumn.id])),
          )

          return [
            column.id,
            [...new Set(availableRows.map((row) => String(column.value(row))))].sort(
              (left, right) => textCollator.compare(left, right),
            ),
          ]
        }),
      ),
    [columns, search, numericFilterValues, numericFilterableColumns, filterValues, rows, serverSide, openFilterColumnId, remoteFilterOptions.options, textFilterableColumns],
  )
  const filteredRows = useMemo(
    () => {
      if (serverSide) {
        return rows
      }

      return rows.filter((row) =>
        matchesTableSearch(row, columns, search) &&
        matchesTableFilters(row, textFilterableColumns, filterValues) &&
        numericFilterableColumns.every((column) =>
          matchesNumericFilter(Number(column.value(row)), numericFilterValues[column.id]),
        ),
      )
    },
    [columns, search, filterValues, numericFilterValues, numericFilterableColumns, rows, serverSide, textFilterableColumns],
  )
  const sortedRows = useMemo(() => {
    if (serverSide || sortState === null) {
      return filteredRows
    }

    const sortedColumn = columns.find((column) => column.id === sortState.columnId)
    if (sortedColumn === undefined || sortedColumn.sortable === false) {
      return filteredRows
    }

    return [...filteredRows].sort((leftRow, rightRow) => {
      const getSortValue = sortedColumn.sortValue ?? sortedColumn.value
      const leftValue = getSortValue(leftRow)
      const rightValue = getSortValue(rightRow)
      const comparison =
        typeof leftValue === 'number' && typeof rightValue === 'number'
          ? leftValue - rightValue
          : textCollator.compare(String(leftValue), String(rightValue))

      return sortState.direction === 'ascending' ? comparison : -comparison
    })
  }, [columns, filteredRows, serverSide, sortState])
  const preserveHorizontalScroll = () => {
    const scroller = scrollRef.current
    if (!scroller) return
    queryScrollRef.current = { left: scroller.scrollLeft, rows, visibleRows: sortedRows }
    const table = scroller.querySelector('table')
    // Keep every column in place, including when the new results have shorter text.
    // Releasing the width after loading lets the browser clamp scrollLeft again.
    if (table) {
      const widths = Array.from(table.querySelectorAll('thead th'), (cell) => cell.getBoundingClientRect().width)
      table.style.minWidth = `${table.getBoundingClientRect().width}px`
      setLockedColumns({ ids: columnIds, widths })
    }
  }
  const footerRow = getFooterRow?.(sortedRows) ?? null
  useLayoutEffect(() => {
    if (openFilterColumnId === null) return
    const anchor = activeFilterMenuRef.current
    const scroller = scrollRef.current
    const menu = filterPopupRef.current
    if (!anchor || !scroller || !menu) return
    const alignLeft = columns.findIndex((column) => column.id === openFilterColumnId) < columns.length / 2

    const positionMenu = () => {
      const anchorBounds = anchor.getBoundingClientRect()
      const leftEdge = 8
      const rightEdge = document.documentElement.clientWidth - 8
      const availableWidth = Math.max(0, rightEdge - leftEdge)
      menu.style.minWidth = `min(13.5rem, ${availableWidth}px)`
      menu.style.maxWidth = `${availableWidth}px`
      const width = menu.getBoundingClientRect().width
      const preferredLeft = alignLeft ? anchorBounds.left : anchorBounds.right - width
      const left = Math.max(leftEdge, Math.min(preferredLeft, rightEdge - width))
      menu.style.left = `${left}px`
      menu.style.right = 'auto'
      const below = Math.max(0, document.documentElement.clientHeight - anchorBounds.bottom - 12)
      const above = Math.max(0, anchorBounds.top - 12)
      const openAbove = below < Math.min(menu.scrollHeight, 320) && above > below
      menu.style.maxHeight = `${Math.min(320, openAbove ? above : below)}px`
      const height = menu.getBoundingClientRect().height
      menu.style.top = `${Math.max(8, openAbove ? anchorBounds.top - height - 4 : anchorBounds.bottom + 4)}px`
    }
    positionMenu()
    const observer = new ResizeObserver(positionMenu)
    observer.observe(scroller)
    observer.observe(menu)
    window.addEventListener('resize', positionMenu)
    window.addEventListener('scroll', positionMenu, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', positionMenu)
      window.removeEventListener('scroll', positionMenu, true)
    }
  }, [columns, openFilterColumnId])

  useLayoutEffect(() => {
    const saved = queryScrollRef.current
    const scroller = scrollRef.current
    if (!saved || !scroller) return
    const complete = !loading && (error || (serverSide ? rows !== saved.rows : sortedRows !== saved.visibleRows))
    scroller.scrollLeft = saved.left
    if (complete) queryScrollRef.current = null
  }, [loading, error, rows, serverSide, sortedRows])

  useLayoutEffect(() => {
    if (loading || error || internalScroll) return
    const element = scrollRef.current
    if (!element) return
    const measure = () => setSettledHeight(element.getBoundingClientRect().height)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [loading, error, internalScroll, sortedRows])


  useEffect(() => {
    if (!searchable || !serverSide) return
    const timeout = window.setTimeout(() => setDebouncedSearch(searchTerm.trim()), 250)
    return () => window.clearTimeout(timeout)
  }, [searchable, searchTerm, serverSide])

  useEffect(() => {
    onQueryChange?.({ filters: queryFilters, sort: sortState, ...(searchable ? { search } : {}) })
  }, [queryFilters, onQueryChange, search, searchable, sortState])

  useEffect(() => {
    if (searchable && scrollRef.current) scrollRef.current.scrollTop = 0
  }, [search, searchable])

  useEffect(() => {
    if (openFilterColumnId === null) {
      return
    }

    function closeFilterMenu(event: MouseEvent) {
      if (event.target instanceof Node && (activeFilterMenuRef.current?.contains(event.target) || filterPopupRef.current?.contains(event.target))) {
        return
      }

      setOpenFilterColumnId(null)
    }

    document.addEventListener('mousedown', closeFilterMenu)
    return () => {
      document.removeEventListener('mousedown', closeFilterMenu)
    }
  }, [openFilterColumnId])

  const matchingRowCount = serverSide ? totalRows ?? sortedRows.length : sortedRows.length
  const canClearFilters = clearableFilters && (
    Object.values(filterValues).some((values) => values.length > 0)
    || Object.values(numericFilterValues).some(hasNumericFilter)
    || (searchable && (searchTerm.trim() !== '' || search !== ''))
  )
  const exportFileName = csvFileName ?? `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'table'}.csv`
  const exportButton = showExport && (
    <button
      className="report-table__export"
      aria-label={exporting ? 'Preparing CSV' : 'Export to CSV'}
      title={exporting ? 'Preparing CSV' : 'Export to CSV'}
      disabled={exporting || loading || searchPending || !!error || sortedRows.length === 0}
      onClick={async () => {
        setExporting(true)
        setExportError(null)
        try {
          const exportRows = getExportRows ? await getExportRows() : sortedRows
          downloadCsv(exportFileName, columns, exportRows)
        } catch {
          setExportError('CSV export failed. Please try again.')
        } finally {
          setExporting(false)
        }
      }}
      type="button"
    >
      <DownloadIcon />
      {exporting ? 'Preparing CSV?' : 'Export to CSV'}
    </button>
  )

  return (
    <section
      aria-busy={loading || searchPending}
      aria-labelledby={titleId}
      className={`report-table ${internalScroll ? 'report-table--internal-scroll' : ''}`}
    >
      <header className="report-table__header">
        <div className="report-table__heading">
          <h2 className="report-table__title" id={titleId}>
            {title}
          </h2>
          {showRowCount && <p className="report-table__subtitle">
            <span role="status" aria-live="polite" aria-atomic="true">
              {loading || searchPending ? 'Updating row count…' : error ? 'Row count unavailable' :
                `Showing ${matchingRowCount.toLocaleString()} ${matchingRowCount === 1 ? 'row' : 'rows'}`}
            </span>
          </p>}
        </div>
        {searchable || canClearFilters || headerActions ? (
          <div className="report-table__header-actions">
            {canClearFilters && (
              <button type="button" className="report-table__clear-filters" onClick={() => {
                preserveHorizontalScroll()
                setFilterValues({})
                setNumericFilterValues({})
                setNumericFilterMessages({})
                setSearchTerm('')
                setDebouncedSearch('')
                setOpenFilterColumnId(null)
                onClearFilters?.()
              }}>Clear filters</button>
            )}
            {searchable && <label className="report-table__search">

              <input
                aria-label={`Search ${title}`}
                maxLength={200}
                onChange={(event) => {
                  preserveHorizontalScroll()
                  setSearchTerm(event.target.value)
                }}
                placeholder="Search all columns…"
                type="search"
                value={searchTerm}
              />
            </label>}
            {headerActions}
            {exportButton}
          </div>
        ) : exportButton}
      </header>
      {exportError && <p role="alert" className="report-status--error">{exportError}</p>}
      <div className={`report-table__scroll${stickyFirstColumn ? ' report-table__scroll--pinned' : ''}${!internalScroll && settledHeight > 0 ? ' report-table__scroll--preserve-height' : ''}`} ref={scrollRef}
        style={!internalScroll && (loading || error) && settledHeight > 0 ? { minHeight: settledHeight } : undefined}>
        <table style={lockedWidths ? { tableLayout: 'fixed', width: lockedWidths.reduce((sum, width) => sum + width, 0), minWidth: lockedWidths.reduce((sum, width) => sum + width, 0) } : undefined} onMouseLeave={highlightColumnOnHover ? () => setHoveredColumn(null) : undefined} className={`report-table__table${stickyFirstColumn && horizontalTrack.content > horizontalTrack.width ? ' report-table__table--sticky-first' : ''}`}>
          <caption className="visually-hidden">{title}</caption>
          {lockedWidths && <colgroup>{lockedWidths.map((width, index) => <col key={columns[index].id} style={{ width }} />)}</colgroup>}
          <thead>
            <tr>
              {columns.map((column) => {
                const isFilterable = column.filterable === true
                const isSortable = column.sortable !== false
                const isSorted = sortState?.columnId === column.id
                const isFilterMenuOpen = openFilterColumnId === column.id
                const direction = isSorted ? sortState.direction : undefined
                const nextDirection =
                  direction === undefined
                    ? column.initialSortDirection ?? 'ascending'
                    : direction === 'ascending'
                      ? 'descending'
                      : 'ascending'
                const className = [
                  'report-table__column-header',
                  column.numeric ? 'report-table__column-header--numeric' : '',
                ]
                  .filter(Boolean)
                  .join(' ')
                const columnFilterOptions = filterOptions.get(column.id) ?? []
                const selectedFilterValues = filterValues[column.id] ?? []
                const numericFilter = numericFilterValues[column.id]
                const isFilterActive =
                  column.numeric === true
                    ? hasNumericFilter(numericFilter)
                    : selectedFilterValues.length > 0
                const filterMenuId = `${titleId}-${column.id}-filter-menu`

                return (
                  <th
                    aria-sort={isSortable ? direction ?? 'none' : undefined}
                    onMouseEnter={highlightColumnOnHover ? (event) => column.highlightOnHover === false ? setHoveredColumn(null) : highlightColumn(event.currentTarget, column.id) : undefined}
                    className={[column.numeric ? 'report-table__numeric' : '', highlightColumnOnHover && column.highlightOnHover !== false && hoveredColumn === column.id ? 'report-table__cell--column-hover' : ''].filter(Boolean).join(' ')}
                    key={column.id}
                    scope="col"
                  >
                    <div className={className}>
                      {isSortable ? (
                        <button
                          aria-label={`Sort by ${column.header} ${nextDirection}`}
                          className="report-table__sort-button"
                          onClick={() => {
                            preserveHorizontalScroll()
                            setSortState({
                              columnId: column.id,
                              direction: nextDirection,
                            })
                          }}
                          type="button"
                        >
                          <span>{column.header}</span>
                          <SortIcon direction={direction} />
                        </button>
                      ) : (
                        <span className="report-table__column-label">{column.header}</span>
                      )}
                      {isFilterable && (
                        <div
                          className="report-table__filter-menu"
                          onKeyDown={(event) => {
                            if (event.key === 'Escape') {
                              event.preventDefault()
                              setOpenFilterColumnId(null)
                              event.currentTarget
                                .querySelector<HTMLButtonElement>('.report-table__filter-button')
                                ?.focus()
                            }
                          }}
                          ref={isFilterMenuOpen ? activeFilterMenuRef : undefined}
                        >
                          <button
                            aria-controls={isFilterMenuOpen ? filterMenuId : undefined}
                            aria-expanded={isFilterMenuOpen}
                            aria-haspopup="dialog"
                            aria-label={`Filter ${column.header}`}
                            className={`report-table__filter-button ${
                              isFilterActive ? 'report-table__filter-button--active' : ''
                            }`}
                            onClick={() => {
                              setOpenFilterColumnId((openColumnId) =>
                                openColumnId === column.id ? null : column.id,
                              )
                            }}
                            type="button"
                          >
                            <FilterIcon />
                          </button>
                          {isFilterMenuOpen && createPortal(
                            <div
                              aria-label={`Filter ${column.header}`}
                              className="report-table__filter-options"
                              ref={filterPopupRef}
                              id={filterMenuId}
                              role="dialog"
                            >
                              {column.numeric === true ? (
                                <NumericFilterControls
                                  filter={numericFilter}
                                  message={numericFilterMessages[column.id]}
                                  onApply={(nextFilter) => {
                                    const nextNumericFilters = {
                                      ...numericFilterValues,
                                      [column.id]: nextFilter,
                                    }
                                    const hasMatches = rows.some(
                                      (row) =>
                                        textFilterableColumns.every((textColumn) => {
                                          const selectedValues = filterValues[textColumn.id]

                                          return (
                                            selectedValues === undefined ||
                                            selectedValues.length === 0 ||
                                            selectedValues.includes(
                                              String(textColumn.value(row)),
                                            )
                                          )
                                        }) &&
                                        numericFilterableColumns.every((numericColumn) =>
                                          matchesNumericFilter(
                                            Number(numericColumn.value(row)),
                                            nextNumericFilters[numericColumn.id],
                                          ),
                                        ),
                                    )

                                    if (!serverSide && !hasMatches && hasNumericFilter(nextFilter)) {
                                      setNumericFilterMessages((currentMessages) => ({
                                        ...currentMessages,
                                        [column.id]: 'No matching values. The table was not filtered.',
                                      }))
                                      return
                                    }

                                    preserveHorizontalScroll()
                                    setNumericFilterValues((currentFilters) => ({
                                      ...currentFilters,
                                      [column.id]: nextNumericFilters[column.id],
                                    }))
                                    setNumericFilterMessages((currentMessages) => ({
                                      ...currentMessages,
                                      [column.id]: undefined,
                                    }))
                                  }}
                                  onClear={() => {
                                    preserveHorizontalScroll()
                                    setNumericFilterValues((currentFilters) => ({
                                      ...currentFilters,
                                      [column.id]: {
                                        operator: 'equal',
                                        primaryValue: '',
                                        secondaryValue: '',
                                      },
                                    }))
                                    setNumericFilterMessages((currentMessages) => ({
                                      ...currentMessages,
                                      [column.id]: undefined,
                                    }))
                                  }}
                                />
                              ) : serverSide && (remoteFilterOptions.loading || remoteFilterOptions.error) ? (
                                <DataState {...remoteFilterOptions} label={`${column.header} filter options`} />
                              ) : (
                                <MultiSelectFilterOptions
                                  label={column.header}
                                  onChange={(nextSelections) => {
                                    preserveHorizontalScroll()
                                    setFilterValues((currentValues) => ({
                                      ...currentValues,
                                      [column.id]: nextSelections,
                                    }))
                                  }}
                                  options={columnFilterOptions.map((option) => ({
                                    label: option,
                                    value: option,
                                  }))}
                                  selectedValues={selectedFilterValues}
                                />
                              )}
                            </div>, document.body
                          )}
                        </div>
                      )}
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {(loading && !(retainRowsWhileLoading && rows.length > 0)) || error ? (
              <tr><td colSpan={columns.length} className="report-table__state">
                <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
              </td></tr>
            ) : sortedRows.length === 0 ? (
              <tr>
                <td className="report-table__empty" colSpan={columns.length}>
                  {search ? 'No rows match your search and selected filters.' : rows.length === 0 ? emptyMessage : 'No rows match the selected filters.'}
                </td>
              </tr>
            ) : (
              sortedRows.map((row) => (
                <tr className={[getRowClassName?.(row), onRowClick ? 'report-table__row--clickable' : ''].filter(Boolean).join(' ')} key={getRowKey(row)}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? event => {
                    if ((event.target as HTMLElement).closest('button, a, input, select, textarea')) return
                    onRowClick(row)
                  } : undefined}
                  onKeyDown={onRowClick ? event => {
                    if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                      event.preventDefault()
                      onRowClick(row)
                    }
                  } : undefined}>
                  {columns.map((column) => {
                    const className = [column.numeric ? 'report-table__numeric' : '', highlightColumnOnHover && column.highlightOnHover !== false && hoveredColumn === column.id ? 'report-table__cell--column-hover' : ''].filter(Boolean).join(' ')
                    const formattedValue = renderTableCell(column, row)

                    return column.isRowHeader ? (
                      <th onMouseEnter={highlightColumnOnHover ? (event) => column.highlightOnHover === false ? setHoveredColumn(null) : highlightColumn(event.currentTarget, column.id) : undefined} className={className} key={column.id} scope="row">
                        {formattedValue}
                      </th>
                    ) : (
                      <td onMouseEnter={highlightColumnOnHover ? (event) => column.highlightOnHover === false ? setHoveredColumn(null) : highlightColumn(event.currentTarget, column.id) : undefined} className={className} key={column.id}>
                        {formattedValue}
                      </td>
                    )
                  })}
                </tr>
              ))
            )}
          </tbody>
          {(!loading || (retainRowsWhileLoading && rows.length > 0)) && !error && footerRow !== null && (
            <tfoot className={stickyFooterRow ? 'report-table__footer--sticky' : undefined}>
              <tr>
                {columns.map((column) => {
                  const className = [column.numeric ? 'report-table__numeric' : '', highlightColumnOnHover && column.highlightOnHover !== false && hoveredColumn === column.id ? 'report-table__cell--column-hover' : ''].filter(Boolean).join(' ')
                  const formattedValue = renderTableCell(column, footerRow)

                  return column.isRowHeader ? (
                    <th onMouseEnter={highlightColumnOnHover ? (event) => column.highlightOnHover === false ? setHoveredColumn(null) : highlightColumn(event.currentTarget, column.id) : undefined} className={className} key={column.id} scope="row">
                      {formattedValue}
                    </th>
                  ) : (
                    <td onMouseEnter={highlightColumnOnHover ? (event) => column.highlightOnHover === false ? setHoveredColumn(null) : highlightColumn(event.currentTarget, column.id) : undefined} className={className} key={column.id}>
                      {formattedValue}
                    </td>
                  )
                })}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {stickyFirstColumn && <div ref={horizontalScrollRef}
        className="report-table__horizontal-scroll" tabIndex={0} role="region"
        aria-label={`${title} scrollable columns`}
        style={{ marginLeft: horizontalTrack.left, width: horizontalTrack.width,
          display: horizontalTrack.width > 0 && horizontalTrack.content > horizontalTrack.width ? undefined : 'none' }}
        onScroll={(event) => {
          if (scrollRef.current && scrollRef.current.scrollLeft !== event.currentTarget.scrollLeft) {
            scrollRef.current.scrollLeft = event.currentTarget.scrollLeft
          }
        }}>
        <div style={{ width: horizontalTrack.content, height: 1 }} />
      </div>}
      {footer}
    </section>
  )
}
