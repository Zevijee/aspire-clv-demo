import { useId, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DataState, type DataStateProps } from '../DataState'

export type DailyChangeItem = {
  date: string; value: number; opening_census: number; closing_census: number
  end_date?: string
}

type DailyChangeChartProps = DataStateProps & {
  title: string
  subtitle: string
  items: DailyChangeItem[]
  interval?: 'day' | 'week' | 'month'
  headerActions?: ReactNode
  height?: number
  onSelect?: (item: DailyChangeItem) => void
}

const dateLabel = (value: string, full = false) => new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', ...(full ? { year: 'numeric' as const } : {}),
  timeZone: 'UTC',
}).format(new Date(`${value}T00:00:00Z`))

export function DailyChangeChart({ title, subtitle, items, loading, error, onRetry, interval = 'day', headerActions, height, onSelect }: DailyChangeChartProps) {
  const titleId = useId()
  const largest = Math.max(1, ...items.map(item => Math.abs(item.value)))
  const step = 10 ** Math.floor(Math.log10(largest))
  const limit = Math.ceil(largest / step) * step
  return <section className="line-chart daily-change-chart" aria-labelledby={titleId} aria-busy={loading}>
    <header className="daily-change-chart__header">
      <div>
      <h2 id={titleId}>{title}</h2>
      <p className="daily-change-chart__subtitle">{subtitle}</p>
      </div>
      {headerActions}
    </header>
    <div className="line-chart__plot daily-change-chart__plot" style={height === undefined ? undefined : { height }}>
      {loading || error || items.length === 0
        ? <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
        : <ResponsiveContainer width="100%" height="100%">
          <BarChart data={items} accessibilityLayer margin={{ top: 24, right: 12, bottom: 12, left: 0 }} barCategoryGap="12%"
            style={{ cursor: onSelect ? 'pointer' : undefined }} onClick={state => {
              if (!onSelect || !state.isTooltipActive) return
              const item = items.find(item => item.date === state.activeLabel)
              if (item) onSelect(item)
            }}>
            <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" strokeDasharray="3 3" />
            <XAxis dataKey="date" axisLine={false} tickLine={false} minTickGap={40}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }} tickFormatter={value => interval === 'month'
                ? new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
                : dateLabel(String(value))} />
            <YAxis domain={[-limit, limit]} allowDecimals={false} axisLine={false} tickLine={false}
              width={36} tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }} />
            <ReferenceLine y={0} stroke="var(--color-border-strong)" />
            <Tooltip content={({ active, payload }) => {
              const item = payload?.[0]?.payload as DailyChangeItem | undefined
              if (!active || !item) return null
              const periodDays = Math.round((Date.parse(item.end_date ?? item.date) - Date.parse(item.date)) / 86400000) + 1
              return <div className="daily-change-tooltip">
                <p className="daily-change-tooltip__date">{new Intl.DateTimeFormat('en-US', {
                  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
                }).formatRange(new Date(`${item.date}T00:00:00Z`), new Date(`${item.end_date ?? item.date}T00:00:00Z`))}
                  {` (${periodDays} ${periodDays === 1 ? 'day' : 'days'})`}
                </p>
                <dl className="daily-change-tooltip__metrics">
                  <div><dt>Open census</dt><dd>{item.opening_census.toLocaleString()}</dd></div>
                  <div><dt>Close census</dt><dd>{item.closing_census.toLocaleString()}</dd></div>
                  <div className="daily-change-tooltip__net"><dt>Net change</dt>
                    <dd className={item.value > 0 ? 'report-table__change--favorable' : item.value < 0 ? 'report-table__change--adverse' : undefined}>
                      {item.value > 0 ? '+' : ''}{item.value.toLocaleString()}
                    </dd>
                  </div>
                </dl>
              </div>
            }}
              cursor={{ fill: 'var(--color-chart-hover)' }} />
            <Bar dataKey="value" name="Net change" radius={2} maxBarSize={36}
              isAnimationActive={false}>
              {items.map(item => <Cell key={item.date} fill={item.value < 0
                ? 'var(--color-table-change-adverse)' : 'var(--color-table-change-favorable)'} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>}
    </div>
  </section>
}
