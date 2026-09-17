import { DataState, type DataStateProps } from '../DataState'
import {
  Bar,
  Cell,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type BarChartRankingItem = {
  label: string
  value: number
}

type BarChartRankingProps = DataStateProps & {
  clearLabel?: string
  categoryLabel: string
  items: BarChartRankingItem[]
  subtitle: string
  selectedLabels?: string[]
  onSelect?: (label: string) => void
  onClear?: () => void
  title: string
  valueLabel: string
}

type RankingTooltipProps = {
  active?: boolean
  label?: string
  payload?: { value?: number }[]
  total: number
}

function RankingTooltip({ active, label, payload, total }: RankingTooltipProps) {
  if (!active || payload?.[0]?.value === undefined) {
    return null
  }

  const value = payload[0].value
  const percentage = total === 0 ? 0 : Math.round((value / total) * 100)

  return (
    <div className="ranking-tooltip">
      <p>{label}</p>
      <span>
        {value.toLocaleString()} ({percentage}%)
      </span>
    </div>
  )
}

export function BarChartRanking({
  loading,
  error,
  onRetry,
  categoryLabel,
  items,
  subtitle,
  title,
  valueLabel,
  selectedLabels = [], onSelect, onClear,
  clearLabel = 'Clear source filter',
}: BarChartRankingProps) {
  const largestValue = Math.max(...items.map((item) => item.value), 1)
  const total = items.reduce((sum, item) => sum + item.value, 0)

  return (
    <section aria-busy={loading} className="bar-chart-ranking" aria-labelledby="bar-chart-ranking-title">
      <h2 id="bar-chart-ranking-title">{title}</h2>
      <p className="bar-chart-ranking__subtitle">{subtitle}
        {selectedLabels.length > 0 && onClear && <> · <button className="donut-chart__legend-select donut-chart__clear-filter" type="button" onClick={onClear}>{clearLabel}</button></>}
      </p>
      {loading || error || items.length === 0 ? (
        <div className="bar-chart-ranking__plot data-state-container">
          <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
        </div>
      ) : <div
        aria-label={`${title}: ${items
          .map((item) => `${item.label}, ${item.value.toLocaleString()} ${valueLabel}`)
          .join('; ')}`}
        className="bar-chart-ranking__plot"
        role="img"
      >
        <ResponsiveContainer height="100%" width="100%">
          <BarChart
            accessibilityLayer={false}
            onClick={onSelect ? (state) => {
              if (state.isTooltipActive && typeof state.activeLabel === 'string') onSelect(state.activeLabel)
            } : undefined}
            style={onSelect ? { cursor: 'pointer' } : undefined}
            data={items}
            layout="vertical"
            margin={{ bottom: 8, left: 0, right: 8, top: 0 }}
          >
            <CartesianGrid
              horizontal={false}
              stroke="var(--color-chart-grid)"
              strokeDasharray="3 3"
            />
            <XAxis
              axisLine={false}
              domain={[0, largestValue]}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 12 }}
              tickLine={false}
              type="number"
            />
            <YAxis
              axisLine={false}
              dataKey="label"
              tick={{ fill: 'var(--color-chart-label)', fontSize: 12 }}
              tickLine={false}
              type="category"
              width={90}
            />
            <Tooltip
              content={<RankingTooltip total={total} />}
              cursor={{ fill: 'var(--color-chart-hover)' }}
            />
            <Bar
              activeBar={false}
              isAnimationActive={!onSelect}
              style={onSelect ? { cursor: 'pointer' } : undefined}
              dataKey="value"
              fill="var(--color-chart-series-primary)"
              radius={[4, 4, 4, 4]}
            >
              {items.map((item) => <Cell key={item.label} fillOpacity={!selectedLabels.length || selectedLabels.includes(item.label) ? 1 : 0.35} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>}
      <table className="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">{categoryLabel}</th>
            <th scope="col">{valueLabel}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.label}>
              <td>{onSelect ? <button type="button" aria-pressed={selectedLabels.includes(item.label)} onClick={() => onSelect(item.label)}>{item.label}</button> : item.label}</td>
              <td>{item.value.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
