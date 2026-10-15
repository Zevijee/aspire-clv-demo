import { useId, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DataState, type DataStateProps } from '../DataState'

export type GainLossItem = {
  date: string
  end_date?: string
  /** What came in over the period, drawn above the line. */
  gain: number
  /** What went out, drawn below it: a count, given as a positive number. */
  loss: number
  /** More to show on hover, after the gain, loss and net. */
  details?: { label: string; value: string }[]
}

type GainLossChartProps = DataStateProps & {
  title: string
  subtitle: string
  items: GainLossItem[]
  gainLabel: string
  lossLabel: string
  interval?: 'day' | 'month'
  height?: number
  headerActions?: ReactNode
}

/** Each period's gain and loss on one bar each side of a zero line -- hires up
 * and departures down, say -- in DailyChangeChart's style, which draws a single
 * net figure each period instead: both directions show, not only what they come
 * to. The axis is the same distance each way, so a gain and a loss of the same
 * size look the same size. */
export function GainLossChart({ title, subtitle, items, gainLabel, lossLabel, interval = 'month', height,
  headerActions, loading, error, onRetry }: GainLossChartProps) {
  const titleId = useId()
  const largest = Math.max(1, ...items.flatMap(item => [item.gain, item.loss]))
  const step = 10 ** Math.floor(Math.log10(largest))
  const limit = Math.ceil(largest / step) * step
  // The loss as a negative height, so it hangs below the line.
  const data = items.map(item => ({ ...item, down: -item.loss }))
  const count = (value: number) => Math.abs(value).toLocaleString()
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
          <BarChart data={data} accessibilityLayer margin={{ top: 24, right: 12, bottom: 12, left: 0 }} barCategoryGap="12%"
            stackOffset="sign">
            <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" strokeDasharray="3 3" />
            <XAxis dataKey="date" axisLine={false} tickLine={false} minTickGap={40}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }} tickFormatter={value => new Intl.DateTimeFormat(
                'en-US', interval === 'month' ? { month: 'short', year: '2-digit', timeZone: 'UTC' }
                  : { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))} />
            {/* Both ways as counts: a loss below the line is not a negative number of people. */}
            <YAxis domain={[-limit, limit]} allowDecimals={false} axisLine={false} tickLine={false} width={44}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }} tickFormatter={value => count(Number(value))} />
            <ReferenceLine y={0} stroke="var(--color-border-strong)" />
            <Tooltip cursor={{ fill: 'var(--color-chart-hover)' }} content={({ active, payload }) => {
              const item = payload?.[0]?.payload as GainLossItem | undefined
              if (!active || !item) return null
              const days = Math.round((Date.parse(item.end_date ?? item.date) - Date.parse(item.date)) / 86400000) + 1
              const net = item.gain - item.loss
              return <div className="daily-change-tooltip">
                <p className="daily-change-tooltip__date">{new Intl.DateTimeFormat('en-US', {
                  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
                }).formatRange(new Date(`${item.date}T00:00:00Z`), new Date(`${item.end_date ?? item.date}T00:00:00Z`))}
                  {` (${days} ${days === 1 ? 'day' : 'days'})`}
                </p>
                <dl className="daily-change-tooltip__metrics">
                  <div><dt>{gainLabel}</dt><dd className="report-table__change--favorable">+{count(item.gain)}</dd></div>
                  <div><dt>{lossLabel}</dt><dd className="report-table__change--adverse">−{count(item.loss)}</dd></div>
                  <div className="daily-change-tooltip__net"><dt>Net change</dt>
                    <dd className={net > 0 ? 'report-table__change--favorable' : net < 0 ? 'report-table__change--adverse'
                      : undefined}>{net > 0 ? '+' : net < 0 ? '−' : ''}{count(net)}</dd>
                  </div>
                  {item.details?.map(detail => <div key={detail.label}><dt>{detail.label}</dt><dd>{detail.value}</dd></div>)}
                </dl>
              </div>
            }} />
            {/* Rounded only at the outer end: flat where the two meet at the line. A
                bar below the line is drawn upside down, so its top corners are the
                ones at its foot. */}
            <Bar dataKey="gain" name={gainLabel} stackId="flow" radius={[2, 2, 0, 0]} maxBarSize={36} isAnimationActive={false}
              fill="var(--color-table-change-favorable)" />
            <Bar dataKey="down" name={lossLabel} stackId="flow" radius={[2, 2, 0, 0]} maxBarSize={36} isAnimationActive={false}
              fill="var(--color-table-change-adverse)" />
          </BarChart>
        </ResponsiveContainer>}
    </div>
  </section>
}
