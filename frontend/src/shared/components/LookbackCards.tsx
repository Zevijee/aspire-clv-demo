import { useState } from 'react'
import { DataState, type DataStateProps } from './DataState'
import { DownloadButton } from './DownloadButton'
import { StatusBadge, type StatusTone } from './StatusBadge'
import { downloadCsv, type TableColumn } from './Table'
import { tableChange, type FavorableChange } from '../utils/tableChange'

/** The drilldown's current scope as one row. With its facilities, the card
 * says how many it covers. */
type LookbackRow = { key: string; name: string; facilities?: readonly unknown[] }

const facilityCount = (row: LookbackRow) => row.facilities === undefined ? null
  : `${row.facilities.length.toLocaleString()} ${row.facilities.length === 1 ? 'facility' : 'facilities'}`

/** The file's name with the scope's before `.csv`, so files from different
 * drilldown levels do not overwrite each other. */
const scopeFileName = (fileName: string, name: string) => {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'location'
  return fileName.replace(/(\.csv)?$/i, `-${slug}.csv`)
}

/** A column after the current one: a past day, or an average over a period. */
export type LookbackPeriod = {
  key: string
  label: string
  /** The day or the dates it covers, shown on hover. */
  title?: string
  /** An average reads with a decimal place where the current value has none. */
  average?: boolean
}

/** One row of the card: the current value, then each period's value with the
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
  /** What the card is, its heading: "Historical look-back". The line beneath
   * says whose total it is and what the columns compare. */
  title: string
  /** With a file name, the card gets a download button: one CSV line per
   * measure, the current value, then each period's value and change. */
  csvFileName?: string
  /** The drilldown's current scope, its facilities summed: all locations at
   * the top, then whatever the drilldown has opened. */
  scope: Row
  measures: LookbackMeasure<Row>[]
  currentLabel: string
  currentTitle?: string
  periods: LookbackPeriod[]
}

/** A look-back of the drilldown's current scope: one full-width card, a small
 * table of measures by period with the current value's change beneath each.
 * Another level's look-back is a drill away, so the card never repeats per
 * location. A report supplies its scope, measures and periods; the card owns
 * layout and the formatting and colouring of changes. */
export function LookbackCards<Row extends LookbackRow>({ title, csvFileName, scope, measures,
  currentLabel, currentTitle, periods, loading, error, onRetry }: LookbackCardsProps<Row>) {
  const [exportError, setExportError] = useState(false)
  const show = (measure: LookbackMeasure<Row>, value: number | null, average = false) =>
    value === null ? '—' : measure.format(value, average)
  // Current minus a past value, signed, in a badge toned as the report tables
  // colour a change: green when favourable, red when adverse, neutral at zero.
  const change = (measure: LookbackMeasure<Row>, current: number | null, then: number | null, average: boolean) => {
    if (current === null || then === null) return null
    const delta = Math.round((current - then) / measure.step) * measure.step
    const { text, className } = tableChange(delta, measure.favorable)
    const tone: StatusTone = className === 'report-table__change--favorable' ? 'success'
      : className === 'report-table__change--adverse' ? 'danger' : 'neutral'
    return <StatusBadge tone={tone} compact>{delta === 0 ? String(text)
      : `${delta > 0 ? '+' : '−'}${(measure.formatChange ?? measure.format)(Math.abs(delta), average)}`}</StatusBadge>
  }

  // One CSV line per measure: what the card shows, with each change as a
  // signed number rather than a coloured badge. An average's column says so,
  // which on the card only its heading does.
  const exportCsv = () => {
    type Line = { row: Row; measure: LookbackMeasure<Row> }
    const lines: Line[] = measures.map(measure => ({ row: scope, measure }))
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
      ...periods.flatMap(({ key, label, average }): TableColumn<Line>[] => {
        const header = average ? `${label} average` : label
        return [
          { id: key, header, value: line => round(line.measure.value(line.row, key), line.measure.step) },
          { id: `${key}-change`, header: `${header} change`, value: line => {
            const current = line.measure.value(line.row, null), then = line.measure.value(line.row, key)
            return current === null || then === null ? '' : round(current - then, line.measure.step)
          } },
        ]
      }),
    ]
    try {
      setExportError(false)
      downloadCsv(scopeFileName(csvFileName!, scope.name), columns, lines)
    } catch {
      setExportError(true)
    }
  }

  // Floating on the page as every report card does, the full width. While
  // loading or after an error, the card holds its place with the state.
  if (loading || error) return <section className="lookback-card lookback-section__state" aria-label={title}
    aria-busy={loading}>
    <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
  </section>

  // What the card is, in words: whose total it is -- the scope the drilldown
  // above has open -- and what its columns compare.
  const count = facilityCount(scope)
  const hasAverages = periods.some(period => period.average)
  const compared = hasAverages ? 'its real value on earlier days and its averages over earlier periods'
    : 'its real value on earlier days'
  return <section className="lookback-card" aria-label={title}>
    <header className="lookback-card__header">
      <div className="lookback-card__heading">
        <h2 className="lookback-card__name">{title}</h2>
        <p className="lookback-card__detail">
          <strong>{scope.name}</strong>{count ? `: the total of the ${count} in the current drilldown` : ''}.
          {' '}The current value against {compared}. Hover a column for its dates.</p>
        {exportError && <p className="lookback-card__detail" role="alert">CSV export failed. Please try again.</p>}
      </div>
      {csvFileName && <DownloadButton label={`Download ${scope.name} look-back as CSV`} onClick={exportCsv} />}
    </header>
    <div className="lookback-card__scroll">
    {/* A measure per row and a period per column, the current one first: each
        past value has the current one's change against it beneath it, so
        every cell reads the same way and none is left empty. */}
    <table className="lookback-card__table">
      <thead><tr>
        <th scope="col" className="lookback-card__measure-heading">Metric</th>
        <th scope="col" className="lookback-card__today" title={currentTitle}>{currentLabel}</th>
        {/* An average says so in its heading: nothing else on the card does. */}
        {periods.map(({ key, label, title, average }) => <th key={key} scope="col"
          title={average && title ? `Average, ${title}` : title}>{average ? `${label} avg.` : label}</th>)}
      </tr></thead>
      <tbody>
        {measures.map(measure => {
          const current = measure.value(scope, null)
          return <tr key={measure.id}>
            <th scope="row">{measure.label}</th>
            {/* Where the other cells have their change, the current one says it
                is what each change is measured from. */}
            <td className="lookback-card__today">{show(measure, current)}
              <span className="lookback-card__change lookback-card__baseline">Baseline</span></td>
            {periods.map(({ key, average = false }) => {
              const then = measure.value(scope, key)
              return <td key={key}>{show(measure, then, average)}
                <span className="lookback-card__change">{change(measure, current, then, average)}</span></td>
            })}
          </tr>
        })}
      </tbody>
    </table>
    </div>
  </section>
}
