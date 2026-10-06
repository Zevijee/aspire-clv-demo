import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DataState, type DataStateProps } from '../DataState'

type Item = { label: string; values: Record<string, number> }
type Series = { id: string; label: string; color: string }

export function StackedRankingChart({ title, subtitle, items, series, onSelect, loading, error, onRetry,
  totalLabel = 'Total' }: DataStateProps & {
  title: string; subtitle?: string; items: Item[]; series: Series[]; onSelect?: (label: string) => void
  /** Names the sum of the parts in the hover tooltip, e.g. "PDPM residents". */
  totalLabel?: string
}) {
  const rows = items.map(item => ({ label: item.label, ...item.values }))
  // Wide enough for the longest name shown, at about 7px a character, so short
  // names such as states leave no empty column beside the bars.
  const labelWidth = Math.min(240, Math.max(32, ...items.map(item => item.label.length * 7 + 12)))
  return <section className="line-chart" aria-busy={loading}>
    <header className="stacked-ranking-chart__header">
      <div><h2>{title}</h2>{subtitle && <p className="daily-change-chart__subtitle">{subtitle}</p>}</div>
      <div aria-label="Chart legend" className="stacked-ranking-chart__legend">
        {series.map(part => <span key={part.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 2, background: part.color }} />
          {part.label}
        </span>)}
      </div>
    </header>
    {loading || error || !items.length ? <DataState loading={loading} error={error} onRetry={onRetry} label={title} /> :
      // Horizontal bars, one row per item, ranked top to bottom. The card grows
      // with the list and the page scrolls; there is no inner scroll area.
      <div>
        <div style={{ height: Math.max(200, items.length * 48 + 40) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 8, bottom: 8, left: 8, right: 32 }}
              style={{ cursor: onSelect ? 'pointer' : undefined }} onClick={state => {
                if (state.isTooltipActive && typeof state.activeLabel === 'string') onSelect?.(state.activeLabel)
              }}>
              <CartesianGrid horizontal={false} stroke="var(--color-chart-grid)" strokeDasharray="3 3" />
              {/* Ends at the largest total, so the leading bar fills the plot. */}
              <XAxis type="number" allowDecimals={false} domain={[0, 'dataMax']} tick={{ fontSize: 11, fill: 'var(--color-chart-axis)' }}
                tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="label" interval={0} width={labelWidth}
                tick={{ fontSize: 12, fill: 'var(--color-text)' }} tickLine={false} axisLine={false} />
              <Tooltip cursor={{ fill: 'var(--color-chart-hover)' }} content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const row = payload[0].payload
                return <div className="daily-change-tooltip">
                  <p className="daily-change-tooltip__date">{row.label}</p>
                  <dl className="daily-change-tooltip__metrics">
                    {series.map(part => <div key={part.id}><dt>{part.label}</dt><dd>{Number(row[part.id]).toLocaleString()}</dd></div>)}
                    <div className="daily-change-tooltip__net"><dt>{totalLabel}</dt><dd>{series.reduce((sum, part) => sum + Number(row[part.id]), 0).toLocaleString()}</dd></div>
                  </dl>
                </div>
              }} />
              {series.map(part => <Bar key={part.id} dataKey={part.id} name={part.label} fill={part.color} stackId="total" maxBarSize={32} isAnimationActive={false}
                // A 2px surface-coloured edge keeps neighbouring sections apart.
                stroke="var(--color-surface)" strokeWidth={2} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>}
  </section>
}
