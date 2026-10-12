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
  /** The line variant's colour, a chart series token; the primary series by default. */
  lineColor?: string
  interval?: 'day' | 'month'
  showDailyAverage?: boolean
  /** Dashed horizontal lines at levels the series is read against -- a
   * target, the edges of an acceptable band -- each with its label; the axis
   * is sized to keep them in view. `adverse` draws a line in the shared
   * adverse colour, for a level it is bad to cross. */
  referenceLines?: { value: number; label: string; tone?: 'neutral' | 'adverse' }[]
  headerActions?: ReactNode
  onSelect?: (item: LineChartItem) => void
  /** How a value reads on the axis and in the tooltip, such as a currency.
   * Without it the axis shows plain numbers and the tooltip grouped ones. */
  formatValue?: (value: number) => string
  /** How a value reads on the axis alone, when formatValue is too wide for it,
   * such as $3.18M for a daily revenue the tooltip shows in full. */
  formatAxis?: (value: number) => string
  /** Bars normally start at zero. `fit` starts them just below the lowest
   * value, for a level such as census that moves a few points on a large
   * base, where zero would flatten every bar to the same height. */
  baseline?: 'zero' | 'fit'
}

export function LineChart({ items, title, subtitle, loading, error, onRetry, signed = false, valueLabel = 'Admissions', variant = 'line', height, barColor = 'var(--color-table-change-favorable)', lineColor = 'var(--color-chart-series-primary)', interval = 'day', showDailyAverage = false, referenceLines = [], headerActions, onSelect, baseline = 'zero', formatValue, formatAxis = formatValue }: LineChartProps) {
  const Chart = variant === 'bar' ? BarChart : RechartsLineChart
  const values = [...items.map((item) => item.value), ...referenceLines.map((line) => line.value)]
  const minimumValue = Math.min(...(values.length ? values : [0]))
  const maximumValue = Math.max(...(values.length ? values : [0]))
  // A tenth of the range above and below. Counts pad by whole units, at
  // least one; a measure with decimals, such as a PPD moving by tenths, pads
  // by its own range, or a whole unit would flatten every dip and peak.
  const whole = values.every((value) => Number.isInteger(value))
  const axisPadding = whole ? Math.max(1, Math.ceil((maximumValue - minimumValue) * 0.1))
    : Math.max((maximumValue - minimumValue) * 0.1, Math.abs(maximumValue) * 0.01)
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
          <Chart data={items} barCategoryGap="12%"
            // Room on the right for reference-line labels drawn outside the plot.
            margin={{ bottom: 8, left: 0, right: referenceLines.length ? 112 : 20, top: 24 }}
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
              // Counts tick by whole numbers; a measure with decimals needs
              // decimal ticks, or a PPD between 2.2 and 2.4 gets one tick at 2.
              allowDecimals={!whole}
              axisLine={false}
              domain={yAxisDomain}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 10 }}
              tickFormatter={formatAxis}
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
                  <dt>{valueLabel}</dt><dd>{formatValue ? formatValue(item.value) : item.value.toLocaleString()}</dd>
                </div>
                  {showDailyAverage && <div><dt>Average per day</dt>
                    {/* In the chart's own format when it has one, such as dollars. */}
                    <dd>{formatValue ? formatValue(item.value / days)
                      : (item.value / days).toLocaleString(undefined, { maximumFractionDigits: 1 })}</dd>
                  </div>}
                </dl>
              </div>
            }} />
            {signed && <ReferenceLine y={0} stroke="var(--color-border-strong)" />}
            {referenceLines.map((line) => {
              const color = line.tone === 'adverse' ? 'var(--color-table-change-adverse)' : 'var(--color-text-muted)'
              return <ReferenceLine key={line.label} y={line.value} stroke={color} strokeDasharray="5 4"
                ifOverflow="extendDomain"
                // Outside the plot, to the right of the line's end: inside it,
                // the series ran over the label on the days it crossed the line.
                label={{ value: line.label, position: 'right', fill: color, fontSize: 11 }} />
            })}
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
              stroke={lineColor}
              strokeWidth={2.5}
              type="monotone"
            />}
          </Chart>
        </ResponsiveContainer>}
      </div>
    </section>
  )
}
