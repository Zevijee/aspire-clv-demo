import type { ReactNode } from 'react'
import { DataState, type DataStateProps } from '../DataState'
import {
  CartesianGrid,
  Bar,
  Cell,
  Line,
  BarChart,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type LineChartItem = {
  date: string
  value: number
  end_date?: string
  color?: string
}

type LineChartProps = DataStateProps & {
  items: LineChartItem[]
  title: string
  subtitle?: string
  signed?: boolean
  valueLabel?: string
  variant?: 'line' | 'bar'
  height?: number
  barColor?: string
  interval?: 'day' | 'month'
  showDailyAverage?: boolean
  headerActions?: ReactNode
  onSelect?: (item: LineChartItem) => void
  /** Bars normally start at zero. `fit` starts them just below the lowest
   * value, for a level such as census that moves a few points on a large
   * base, where zero would flatten every bar to the same height. */
  baseline?: 'zero' | 'fit'
}

export function LineChart({ items, title, subtitle, loading, error, onRetry, signed = false, valueLabel = 'Admissions', variant = 'line', height, barColor = 'var(--color-table-change-favorable)', interval = 'day', showDailyAverage = false, headerActions, onSelect, baseline = 'zero' }: LineChartProps) {
  const Chart = variant === 'bar' ? BarChart : RechartsLineChart
  const values = items.map((item) => item.value)
  const minimumValue = Math.min(...(values.length ? values : [0]))
  const maximumValue = Math.max(...(values.length ? values : [0]))
  const axisPadding = Math.max(1, Math.ceil((maximumValue - minimumValue) * 0.1))
  const yAxisDomain: [number, number] = [
    signed ? Math.min(0, minimumValue - axisPadding)
      // A fitted baseline leaves the lowest bar about a third of the range tall.
      : variant === 'bar' && baseline === 'fit' ? Math.max(0, Math.floor(minimumValue - Math.max(1, (maximumValue - minimumValue) / 2)))
      : variant === 'bar' ? 0 : Math.max(0, minimumValue - axisPadding),
    signed ? Math.max(0, maximumValue + axisPadding) : maximumValue + axisPadding,
  ]

  return (
    <section aria-busy={loading} className="line-chart">
      <header className="daily-change-chart__header">
        <div>
        <h2>{title}</h2>
        {subtitle && <p className="daily-change-chart__subtitle">{subtitle}</p>}
        </div>
        {headerActions}
      </header>
      <div className="line-chart__plot" style={height === undefined ? undefined : { height }}>
        {loading || error || items.length === 0 ? (
          <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
        ) : <ResponsiveContainer height="100%" width="100%">
          <Chart data={items} barCategoryGap="12%" margin={{ bottom: 8, left: 0, right: 20, top: 24 }}
            style={{ cursor: onSelect ? 'pointer' : undefined }}
            onClick={state => {
              if (!onSelect || !state.isTooltipActive) return
              const item = items.find(item => item.date === state.activeLabel)
              if (item) onSelect(item)
            }}>
            <CartesianGrid
              horizontal
              stroke="var(--color-border-subtle)"
              strokeDasharray="3 3"
              vertical={false}
            />
            <XAxis
              axisLine={false}
              dataKey="date"
              minTickGap={36}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }}
              tickLine={false}
              tickFormatter={(value: string) =>
                new Intl.DateTimeFormat(undefined, interval === 'month' ? { month: 'short', year: '2-digit' } : { month: 'short', day: 'numeric' }).format(
                  new Date(`${value}T00:00:00`),
                )
              }
            />
            <YAxis
              allowDecimals={false}
              axisLine={false}
              domain={yAxisDomain}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }}
              tickLine={false}
              width={52}
            />
            <Tooltip cursor={variant === 'bar' ? { fill: 'var(--color-chart-hover)' } : undefined} content={({ active, payload }) => {
              const item = payload?.[0]?.payload as LineChartItem | undefined
              if (!active || !item) return null
              const end = item.end_date ?? item.date
              const days = Math.round((Date.parse(end) - Date.parse(item.date)) / 86400000) + 1
              const dates = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
                .formatRange(new Date(`${item.date}T00:00:00Z`), new Date(`${end}T00:00:00Z`))
              return <div className="daily-change-tooltip">
                <p className="daily-change-tooltip__date">{dates} ({days} {days === 1 ? 'day' : 'days'})</p>
                <dl className="daily-change-tooltip__metrics"><div>
                  <dt>{valueLabel}</dt><dd>{item.value.toLocaleString()}</dd>
                </div>
                  {showDailyAverage && <div><dt>Average per day</dt>
                    <dd>{(item.value / days).toLocaleString(undefined, { maximumFractionDigits: 1 })}</dd>
                  </div>}
                </dl>
              </div>
            }} />
            {signed && <ReferenceLine y={0} stroke="var(--color-border-strong)" />}
            {variant === 'bar' ? <Bar dataKey="value" name={valueLabel}
              fill={barColor} radius={[2, 2, 0, 0]}
              maxBarSize={36} isAnimationActive={false}>
              {items.map(item => <Cell key={item.date} fill={item.color ?? (signed
                ? item.value < 0 ? 'var(--color-table-change-adverse)' : 'var(--color-table-change-favorable)'
                : barColor)} />)}
            </Bar> : <Line
              dataKey="value"
              dot={false}
              name={valueLabel}
              stroke="var(--color-chart-series-primary)"
              strokeWidth={2.5}
              type="monotone"
            />}
          </Chart>
        </ResponsiveContainer>}
      </div>
    </section>
  )
}
