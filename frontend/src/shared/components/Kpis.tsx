import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { DataState, type DataStateProps } from './DataState'

// A card's narrowest width, in px: 11rem, matching .kpi's min-width.
const CARD_MIN_WIDTH = 176

/** Columns for stacked cards: as few rows as the width allows, then the cards
 * spread evenly over them, so 12 cards where 8 fit make two rows of 6, not 8
 * and 4. */
function useBalancedColumns(count: number, enabled: boolean) {
  const ref = useRef<HTMLElement>(null)
  const [columns, setColumns] = useState(count)
  useLayoutEffect(() => {
    const element = ref.current
    if (!enabled || !element) return
    const measure = () => {
      const gap = parseFloat(getComputedStyle(element).columnGap) || 0
      const fit = Math.max(1, Math.floor((element.clientWidth + gap) / (CARD_MIN_WIDTH + gap)))
      const rows = Math.ceil(count / fit)
      setColumns(Math.max(1, Math.ceil(count / rows)))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [count, enabled])
  return { ref, columns }
}

export type KpiTrend = {
  direction?: 'up' | 'down' | 'flat'
  label: string
  tone: 'positive' | 'negative' | 'neutral'
  value: string
}

export type KpiItem = {
  header: string
  trend: KpiTrend
  value: string
  /** A colour token for a small square before the header, when the card stands
   * for a category that has the same colour in the report's charts. */
  marker?: string
}

type KpisProps = DataStateProps & {
  items: KpiItem[]
  /** Stack onto further rows instead of scrolling one row sideways, for a set
   * of cards too long to fit, such as twelve SLP groups. Rows are balanced and
   * always full width. */
  stack?: boolean
}

function TrendIcon({ direction }: { direction: KpiTrend['direction'] }) {
  if (direction === 'up') {
    return (
      <svg
        aria-hidden="true"
        className="kpi__trend-icon"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        viewBox="0 0 24 24"
      >
        <path d="M16 7h6v6" />
        <path d="m22 7-8.5 8.5-5-5L2 17" />
      </svg>
    )
  }

  if (direction === 'down') {
    return (
      <svg
        aria-hidden="true"
        className="kpi__trend-icon"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        viewBox="0 0 24 24"
      >
        <path d="M16 17h6v-6" />
        <path d="m22 17-8.5-8.5-5 5L2 7" />
      </svg>
    )
  }

  return (
    <svg
      aria-hidden="true"
      className="kpi__trend-icon"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeWidth={2}
      viewBox="0 0 24 24"
    >
      <path d="M5 12h14" />
    </svg>
  )
}

export function Kpis({ items, loading, error, onRetry, stack = false }: KpisProps) {
  const { ref, columns } = useBalancedColumns(items.length, stack)
  return (
    <section aria-label="Key performance indicators" ref={ref}
      className={`kpis${stack ? ' kpis--stack' : ''}`}
      style={stack ? { '--kpi-columns': columns } as CSSProperties : undefined}>
      {items.map((item) => (
        <article aria-busy={loading} className="kpi" key={item.header}>
          <h2 className="kpi__header">
            {item.marker && <span aria-hidden="true" className="kpi__marker" style={{ background: item.marker }} />}
            {item.header}
          </h2>
          {loading || error ? (
            <div className="kpi__body">
              <DataState loading={loading} error={error} onRetry={onRetry} label={item.header} />
            </div>
          ) : (
              <>
                <p className="kpi__value">{item.value}</p>
                <div className={`kpi__trend kpi__trend--${item.trend.tone}`}>
                  {item.trend.direction && <TrendIcon direction={item.trend.direction} />}
                  {item.trend.value && <span className="kpi__trend-value">{item.trend.value}</span>}
                  <span className="kpi__trend-label">{item.trend.label}</span>
                </div>
              </>
          )}
        </article>
      ))}
    </section>
  )
}
