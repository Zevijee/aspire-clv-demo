import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useState, type ReactNode } from 'react'
import { DataState, type DataStateProps } from '../DataState'

type Item = {
  label: string; values: Record<string, number>
  /** The whole each part's share is of, when the parts overlap and so do not
   * sum to it. Defaults to the sum of the parts. */
  total?: number
}
type Series = { id: string; label: string; color: string }

export function StackedRankingChart({ title, subtitle, items, series, onSelect, loading, error, onRetry,
  totalLabel = 'Total', headerActions, hideLegend = false, onSegmentSelect }: DataStateProps & {
  title: string; subtitle?: string; items: Item[]; series: Series[]; onSelect?: (label: string) => void
  /** Names the sum of the parts in the hover tooltip, e.g. "PDPM residents". */
  totalLabel?: string
  /** Buttons at the right of the header, such as a table view. */
  headerActions?: ReactNode
  /** Leave out the legend when the page already keys every colour, as KPI
   * cards with colour markers do. The tooltip still names each part. */
  hideLegend?: boolean
  /** A click on one segment: the row's label and the part's series id. */
  onSegmentSelect?: (label: string, partId: string) => void
}) {
  const rows = items.map(item => ({ label: item.label, ...item.values,
    __total: item.total ?? series.reduce((sum, part) => sum + (item.values[part.id] ?? 0), 0) }))
  // The segment under the pointer; every other segment fades so it stands out.
  const [hovered, setHovered] = useState<{ row: number; part: string } | null>(null)
  // Wide enough for the longest name shown, at about 7px a character, so short
  // names such as states leave no empty column beside the bars.
  const labelWidth = Math.min(240, Math.max(32, ...items.map(item => item.label.length * 7 + 12)))
  return <section className="line-chart" aria-busy={loading}>
    <header className="stacked-ranking-chart__header">
      <div><h2>{title}</h2>{subtitle && <p className="daily-change-chart__subtitle">{subtitle}</p>}</div>
      {hideLegend ? <div /> : <div aria-label="Chart legend" className="stacked-ranking-chart__legend">
        {series.map(part => <span key={part.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 2, background: part.color }} />
          {part.label}
        </span>)}
      </div>}
      {headerActions && <div className="stacked-ranking-chart__actions">{headerActions}</div>}
    </header>
    {loading || error || !items.length ? <DataState loading={loading} error={error} onRetry={onRetry} label={title} /> :
      // Horizontal bars, one row per item, ranked top to bottom. The card grows
      // with the list and the page scrolls; there is no inner scroll area.
      <div>
        <div style={{ height: Math.max(200, items.length * 56 + 40) }}>
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
              {/* Per segment, not per row: the tooltip names the part under the
                  pointer, its count and its share of the row's whole. */}
              <Tooltip shared={false} cursor={false} content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const row = payload[0].payload
                const part = series.find(item => item.id === payload[0].dataKey)
                if (!part) return null
                const value = Number(row[part.id])
                const rowTotal = Number(row.__total)
                const share = rowTotal > 0 ? `${(value / rowTotal * 100).toLocaleString(undefined,
                  { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : '—'
                return <div className="daily-change-tooltip">
                  <p className="daily-change-tooltip__date">{row.label}</p>
                  <dl className="daily-change-tooltip__metrics">
                    <div><dt style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 2, background: part.color }} />
                      {part.label}</dt><dd>{value.toLocaleString()}</dd></div>
                    <div><dt>Share of {totalLabel}</dt><dd>{share}</dd></div>
                  </dl>
                </div>
              }} />
              {series.map(part => <Bar key={part.id} dataKey={part.id} name={part.label} fill={part.color} stackId="total" maxBarSize={40} isAnimationActive={false}
                // A 2px surface-coloured edge keeps neighbouring sections apart.
                stroke="var(--color-surface)" strokeWidth={2} activeBar={false}
                onMouseEnter={(_, index) => setHovered({ row: index, part: part.id })}
                onMouseLeave={() => setHovered(null)}
                onClick={onSegmentSelect ? (_, index) => onSegmentSelect(rows[index].label, part.id) : undefined}
                style={onSegmentSelect ? { cursor: 'pointer' } : undefined}>
                {rows.map((row, index) => <Cell key={row.label} fillOpacity={
                  !hovered || (hovered.row === index && hovered.part === part.id) ? 1 : 0.35} />)}
              </Bar>)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>}
  </section>
}
