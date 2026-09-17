import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DataState, type DataStateProps } from '../DataState'

type Item = { label: string; values: Record<string, number> }
type Series = { id: string; label: string; color: string }

export function StackedRankingChart({ title, subtitle, items, series, onSelect, loading, error, onRetry }: DataStateProps & {
  title: string; subtitle: string; items: Item[]; series: Series[]; onSelect?: (label: string) => void
}) {
  const rows = items.map(item => ({ label: item.label, ...item.values }))
  return <section className="line-chart" aria-busy={loading}>
    <header className="stacked-ranking-chart__header">
      <div><h2>{title}</h2><p className="daily-change-chart__subtitle">{subtitle}</p></div>
      <div aria-label="Chart legend" className="stacked-ranking-chart__legend">
        {series.map(part => <span key={part.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 2, background: part.color }} />
          {part.label}
        </span>)}
      </div>
    </header>
    {loading || error || !items.length ? <DataState loading={loading} error={error} onRetry={onRetry} label={title} /> :
      <div style={{ maxHeight: 640, overflow: 'auto' }}>
        <div style={{ height: 480, minWidth: Math.max(600, items.length * 90) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 24, bottom: 16, left: 12, right: 32 }}
              style={{ cursor: onSelect ? 'pointer' : undefined }} onClick={state => {
                if (state.isTooltipActive && typeof state.activeLabel === 'string') onSelect?.(state.activeLabel)
              }}>
              <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" strokeDasharray="3 3" />
              <XAxis type="category" dataKey="label" interval={0} height={130} angle={-40} textAnchor="end"
                tick={{ fontSize: 11, fill: 'var(--color-text)' }} tickLine={false} axisLine={false} />
              <YAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--color-chart-axis)' }} />
              <Tooltip cursor={{ fill: 'var(--color-chart-hover)' }} content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const row = payload[0].payload
                return <div className="daily-change-tooltip">
                  <p className="daily-change-tooltip__date">{row.label}</p>
                  <dl className="daily-change-tooltip__metrics">
                    {series.map(part => <div key={part.id}><dt>{part.label}</dt><dd>{Number(row[part.id]).toLocaleString()}</dd></div>)}
                    <div className="daily-change-tooltip__net"><dt>Total admissions</dt><dd>{series.reduce((sum, part) => sum + Number(row[part.id]), 0).toLocaleString()}</dd></div>
                  </dl>
                </div>
              }} />
              {series.map(part => <Bar key={part.id} dataKey={part.id} name={part.label} fill={part.color} stackId="total" maxBarSize={36} isAnimationActive={false} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>}
  </section>
}
