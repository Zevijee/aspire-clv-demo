import { DataState, type DataStateProps } from './DataState'

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
}

type KpisProps = DataStateProps & {
  items: KpiItem[]
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

export function Kpis({ items, loading, error, onRetry }: KpisProps) {
  return (
    <section aria-label="Key performance indicators" className="kpis">
      {items.map((item) => (
        <article aria-busy={loading} className="kpi" key={item.header}>
          <h2 className="kpi__header">{item.header}</h2>
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
