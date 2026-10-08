import { useId, useState } from 'react'
import { DataState, type DataStateProps } from './DataState'
import { DownloadIcon, downloadCsv, type TableColumn } from './Table'
import { tableChange, type FavorableChange } from '../utils/tableChange'

/** Any row a drilldown already has: a location, or the scope as one row. */
type LookbackRow = { key: string; name: string }

/** A column after the current one: a past day, or an average over a period. */
export type LookbackPeriod = {
  key: string
  label: string
  /** The day or the dates it covers, shown on hover. */
  title?: string
  /** An average reads with a decimal place where the current value has none. */
  average?: boolean
}

/** One row of every card: the current value, then each period's value with the
 * current minus it beneath. */
export type LookbackMeasure<Row> = {
  id: string
  label: string
  favorable: FavorableChange
  /** The value at this row's scope; `null` period is the current one. Null
   * when unknown, such as a day never generated. Sum the scope's facilities
   * first and divide once: never average facility ratios. */
  value: (row: Row, period: string | null) => number | null
  /** A value, or the size of a change, for display. */
  format: (value: number, average: boolean) => string
  /** The size of a change, when it reads differently from a value, such as
   * percentage points for a percentage. `format` by default. */
  formatChange?: (value: number, average: boolean) => string
  /** The step a change is rounded to, so float noise never shows as a change. */
  step: number
}

type LookbackCardsProps<Row extends LookbackRow> = DataStateProps & {
  /** The outer card's heading, such as "State census history". */
  title: string
  /** A line under the heading saying what the cards compare. */
  subtitle?: string
  /** With a file name, the header gets an Export to CSV button: one line per
   * card and measure, the current value, then each period's value and change. */
  csvFileName?: string
  /** The locations at the drilldown's current level. */
  rows: Row[]
  /** Their scope as one row, leading when there is more than one location and
   * always named "Total" on its card. */
  total: Row
  measures: LookbackMeasure<Row>[]
  currentLabel: string
  currentTitle?: string
  periods: LookbackPeriod[]
}

/** A look-back as one outer card holding a card per location, two to a row,
 * the scope's own total first, each a small table of measures by period. A
 * report supplies its rows, measures and periods; the cards own layout and
 * the formatting and colouring of changes. */
export function LookbackCards<Row extends LookbackRow>({ title, subtitle, csvFileName, rows, total, measures,
  currentLabel, currentTitle, periods, loading, error, onRetry }: LookbackCardsProps<Row>) {
  const titleId = useId()
  const [exportError, setExportError] = useState<string | null>(null)
  // A single location is its own total, so it gets no second card -- the rule
  // the drilldown table follows for its Total row.
  const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name))
  const cards = sorted.length > 1 ? [total, ...sorted] : sorted
  const show = (measure: LookbackMeasure<Row>, value: number | null, average = false) =>
    value === null ? '—' : measure.format(value, average)
  // Current minus a past value, signed and coloured as the report tables do.
  const change = (measure: LookbackMeasure<Row>, current: number | null, then: number | null, average: boolean) => {
    if (current === null || then === null) return null
    const delta = Math.round((current - then) / measure.step) * measure.step
    const { text, className } = tableChange(delta, measure.favorable)
    return <span className={className}>({delta === 0 ? text
      : `${delta > 0 ? '+' : '−'}${(measure.formatChange ?? measure.format)(Math.abs(delta), average)}`})</span>
  }

  // The name sits above its card, outside it; the card is the table alone,
  // its lines running to the card's border.
  const card = (row: Row) => <article key={row.key} className="lookback-card-group">
    {/* Plain names: the drilldown above chooses the level. The scope's own
        card is always "Total", as the table's total row is -- the breadcrumb
        already says where you are -- and stands out a little. */}
    <h3 className={`lookback-card__name${row === total ? ' lookback-card__name--total' : ''}`}>
      {row === total ? 'Total' : row.name}</h3>
    <div className="lookback-card">
    {/* A measure per row and a period per column, the current one first: each
        past value has the current one's change against it beside it in
        brackets, so every cell reads the same way and none is left empty. */}
    <table className="lookback-card__table">
      <thead><tr>
        <th scope="col" className="lookback-card__measure-heading">Metric</th>
        <th scope="col" className="lookback-card__today" title={currentTitle}>{currentLabel}</th>
        {periods.map(({ key, label, title }) => <th key={key} scope="col" title={title}>{label}</th>)}
      </tr></thead>
      <tbody>
        {measures.map(measure => {
          const current = measure.value(row, null)
          return <tr key={measure.id}>
            <th scope="row">{measure.label}</th>
            <td className="lookback-card__today">{show(measure, current)}</td>
            {periods.map(({ key, average = false }) => {
              const then = measure.value(row, key)
              return <td key={key}>{show(measure, then, average)}
                <span className="lookback-card__change">{change(measure, current, then, average)}</span></td>
            })}
          </tr>
        })}
      </tbody>
    </table>
    </div>
  </article>

  // One CSV line per card and measure, in the cards' order: what the cards show,
  // with each change as a signed number rather than coloured text.
  const exportCsv = () => {
    type Line = { row: Row; measure: LookbackMeasure<Row> }
    const lines: Line[] = cards.flatMap(row => measures.map(measure => ({ row, measure })))
    // To the measure's step and no further, so float noise (323.20000000000005)
    // never reaches the file; at least one decimal for an average's tenths.
    const round = (value: number | null, step: number) => {
      if (value === null) return ''
      const decimals = Math.max(1, Math.ceil(-Math.log10(step)))
      return Number(value.toFixed(decimals))
    }
    const columns: TableColumn<Line>[] = [
      { id: 'location', header: 'Location', value: line => line.row.name },
      { id: 'metric', header: 'Metric', value: line => line.measure.label },
      { id: 'current', header: currentLabel, value: line => round(line.measure.value(line.row, null), line.measure.step) },
      ...periods.flatMap(({ key, label }): TableColumn<Line>[] => [
        { id: key, header: label, value: line => round(line.measure.value(line.row, key), line.measure.step) },
        { id: `${key}-change`, header: `${label} change`, value: line => {
          const current = line.measure.value(line.row, null), then = line.measure.value(line.row, key)
          return current === null || then === null ? '' : round(current - then, line.measure.step)
        } },
      ]),
    ]
    try {
      setExportError(null)
      downloadCsv(csvFileName!, columns, lines)
    } catch {
      setExportError('CSV export failed. Please try again.')
    }
  }

  return <section className="lookback-section" aria-labelledby={titleId} aria-busy={loading}>
    {/* A white bar, ruled off from the tinted cards, as the report tables' headers are. */}
    <header className="lookback-section__header">
      <div>
        <h2 id={titleId} className="lookback-section__title">{title}</h2>
        {subtitle && <p className="lookback-section__subtitle">{subtitle}</p>}
        {exportError && <p className="lookback-section__subtitle" role="alert">{exportError}</p>}
      </div>
      {csvFileName && <button type="button" className="report-table__export" title="Export to CSV"
        disabled={loading || !!error || cards.length === 0} onClick={exportCsv}>
        <DownloadIcon />Export to CSV
      </button>}
    </header>
    {loading || error
      ? <div className="lookback-section__state"><DataState loading={loading} error={error} onRetry={onRetry} label={title} /></div>
      : <div className={`lookback-cards${cards.length === 1 ? ' lookback-cards--single' : ''}`}>{cards.map(card)}</div>}
  </section>
}
