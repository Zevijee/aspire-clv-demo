import { useId, type ReactNode } from 'react'
import { DataState, type DataStateProps } from '../DataState'

type DivergingBarItem = { id: string; label: string; value: number }
type DivergingBarChartProps = DataStateProps & {
  title: string
  subtitle: string
  items: DivergingBarItem[]
  onSelect?: (id: string) => void
  selectedIds?: string[]
  headerActions?: ReactNode
}

export function DivergingBarChart({ title, subtitle, items, onSelect, selectedIds = [], headerActions,
  loading, error, onRetry }: DivergingBarChartProps) {
  const titleId = useId()
  const ranked = [...items].sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  const limit = Math.max(1, ...items.map((item) => Math.abs(item.value)))
  return <section className="diverging-chart" aria-labelledby={titleId} aria-busy={loading}>
    <header className="diverging-chart__header">
      <div><h2 id={titleId}>{title}</h2>
        <p>{subtitle}</p></div>
      {headerActions && <div className="report-table__header-actions">{headerActions}</div>}
    </header>
    {loading || error || items.length === 0 ?
      <div className="diverging-chart__state data-state-container">
        <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
      </div> : <>
        <div className="diverging-chart__axis-heading" aria-hidden="true">
          <div className="diverging-chart__axis">
            <span>Negative</span><span>0</span><span>Positive</span>
          </div>
        </div>
        <ul className="diverging-chart__rows">
          {ranked.map((item) => {
            const width = Math.abs(item.value) / limit * 50
            const tone = item.value > 0 ? 'positive' : item.value < 0 ? 'negative' : 'zero'
            return <li className={`diverging-chart__row diverging-chart__row--${tone}${selectedIds.includes(item.id) ? ' diverging-chart__row--selected' : ''}`} key={item.id}>
              <span className="diverging-chart__label">
                {item.label}
              </span>
              <span className="diverging-chart__track" aria-hidden="true">
                <span className="diverging-chart__bar" style={{ width: `${width}%`,
                  left: `${item.value < 0 ? 50 - width : 50}%` }} />
              </span>
              <span className="diverging-chart__value">
                {item.value > 0 ? '+' : ''}{item.value.toLocaleString()}
              </span>
              {onSelect && <button type="button" className="diverging-chart__row-select"
                aria-label={`Filter by ${item.label}, net change ${item.value}`}
                aria-pressed={selectedIds.includes(item.id)}
                onClick={() => onSelect(item.id)} />}
            </li>
          })}
        </ul>
      </>}
  </section>
}
