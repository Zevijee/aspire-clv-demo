import { useId } from 'react'
import { DataState, type DataStateProps } from '../DataState'
import { useAnnounceFilters } from '../../activeFilters'
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
  /** What a selection filters, for "Clear destination filter". Sources by default. */
  filterName?: { one: string; many: string }
  categoryLabel: string
  items: BarChartRankingItem[]
  subtitle: string
  selectedLabels?: string[]
  onSelect?: (label: string) => void
  onClear?: () => void
  title: string
  valueLabel: string
  // For values that are not counts, such as a rate. Share of total is only
  // meaningful when the values add up to something, so it can be turned off.
  formatValue?: (value: number) => string
  showShare?: boolean
  /** Bars normally start at zero. `fit` starts them just below the lowest
   * value, for a level such as occupancy that differs by a few points on a
   * large base, where zero would draw every bar the same length. */
  baseline?: 'zero' | 'fit'
}

type RankingTooltipProps = {
  active?: boolean
  label?: string
  payload?: { value?: number }[]
  total: number
  formatValue: (value: number) => string
  showShare: boolean
}

function RankingTooltip({ active, label, payload, total, formatValue, showShare }: RankingTooltipProps) {
  if (!active || payload?.[0]?.value === undefined) {
    return null
  }

  const value = payload[0].value
  const percentage = total === 0 ? 0 : Math.round((value / total) * 100)

  return (
    <div className="ranking-tooltip">
      <p>{label}</p>
      <span>
        {formatValue(value)}{showShare && ` (${percentage}%)`}
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
  filterName = { one: 'source', many: 'sources' },
  formatValue: axisFormat,
  showShare = true,
  baseline = 'zero',
}: BarChartRankingProps) {
  // A selection that filters the report is a report filter, listed in the drilldown bar.
  // A chart with a clear action is a filter whether or not anything is selected.
  useAnnounceFilters(onClear ? [{ name: filterName.one, active: selectedLabels.length > 0,
    clear: () => onClear(), kind: 'chart' }] : [])
  // Unique per chart: several rankings on one page each label their own section.
  const titleId = useId()
  const formatValue = axisFormat ?? ((value: number) => value.toLocaleString())
  const largestValue = Math.max(...items.map((item) => item.value), 1)
  const smallestValue = Math.min(...items.map((item) => item.value), largestValue)
  // As LineChart fits its bars: the shortest bar is about a third of the longest.
  const lowestValue = baseline === 'fit'
    ? Math.max(0, Math.floor(smallestValue - Math.max(1, (largestValue - smallestValue) / 2))) : 0
  const total = items.reduce((sum, item) => sum + item.value, 0)

  return (
    <section aria-busy={loading} className="bar-chart-ranking" aria-labelledby={titleId}>
      <h2 id={titleId}>{title}</h2>
      <p className="bar-chart-ranking__subtitle">{subtitle}
        {selectedLabels.length > 0 && onClear && <> · <button className="donut-chart__legend-select donut-chart__clear-filter" type="button" onClick={onClear}>Clear {filterName.one} filter</button></>}
      </p>
      {loading || error || items.length === 0 ? (
        <div className="bar-chart-ranking__plot data-state-container">
          <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
        </div>
      ) : <div
        aria-label={`${title}: ${items
          .map((item) => `${item.label}, ${formatValue(item.value)} ${valueLabel}`)
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
              domain={[lowestValue, largestValue]}
              tick={{ fill: 'var(--color-chart-axis)', fontSize: 12 }}
              tickFormatter={axisFormat}
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
              content={<RankingTooltip total={total} formatValue={formatValue} showShare={showShare} />}
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
              <td>{formatValue(item.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
