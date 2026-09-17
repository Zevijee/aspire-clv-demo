import { DataState, type DataStateProps } from '../DataState'
import { useId, useState, type ReactNode } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'

type DonutChartItem = {
  label: string
  value: number
}

type DonutChartProps = DataStateProps & {
  items: DonutChartItem[]
  subtitle: string
  title: string
  titleContent?: ReactNode
  valueLabel?: string
  centerMode?: 'active' | 'total'
  selectedLabels?: string[]
  onClear?: () => void
  onSelect?: (label: string) => void
}

const chartColors = [
  'var(--color-chart-series-primary)',
  'var(--color-chart-series-secondary)',
  'var(--color-chart-series-tertiary)',
  'var(--color-chart-series-quaternary)',
  'var(--color-chart-series-quinary)',
  'var(--color-chart-series-senary)',
  'var(--color-chart-series-septenary)',
]

export function DonutChart({ items, subtitle, title, titleContent, loading, error, onRetry, selectedLabels = [], onClear, onSelect, valueLabel = 'Admissions', centerMode = 'active' }: DonutChartProps) {
  const titleId = useId()
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const total = items.reduce((sum, item) => sum + item.value, 0)
  const hasSelection = selectedLabels.length > 0
  const selectionLabel = selectedLabels.length === 1 ? selectedLabels[0] : `${selectedLabels.length} payers selected`
  const activeItem = hasSelection
    ? { label: selectionLabel, value: items.filter((item) => selectedLabels.includes(item.label)).reduce((sum, item) => sum + item.value, 0) }
    : activeIndex === null ? null : (items[activeIndex] ?? null)

  return (
    <section aria-busy={loading} className="donut-chart" aria-labelledby={titleId}>
      <h2 id={titleId} className={titleContent ? 'donut-chart__title--mixed' : undefined}>
        {titleContent ?? title}
      </h2>
      <p className="donut-chart__subtitle">{subtitle}
        {hasSelection && onClear && <> ? <button className="donut-chart__legend-select donut-chart__clear-filter" type="button"
          onClick={onClear}>Clear payer filter</button></>}
      </p>
      {loading || error || total === 0 ? (
        <div className="donut-chart__content data-state-container">
          <DataState loading={loading} error={error} onRetry={onRetry} label={title} />
        </div>
      ) : <div className="donut-chart__content">
        <div
          aria-label={`${title}: ${items
            .map((item) => `${item.label}, ${item.value.toLocaleString()}`)
            .join('; ')}`}
          onPointerDownCapture={onSelect ? (event) => {
            if (event.button !== 0) return
            const target = event.target as Element
            const sector = target.closest('.recharts-pie-sector')
            if (!sector) return
            const index = Array.from(event.currentTarget.querySelectorAll('.recharts-pie-sector')).indexOf(sector)
            if (items[index]) onSelect(items[index].label)
          } : undefined}
          className="donut-chart__plot"
          role="img"
        >
          <ResponsiveContainer height="100%" width="100%">
            <PieChart>
              <Pie
                data={items}
                isAnimationActive={!onSelect}
                dataKey="value"
                innerRadius="61%"
                nameKey="label"
                onMouseEnter={(_, index) => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(null)}
                style={onSelect ? { cursor: 'pointer' } : undefined}
                outerRadius="96%"
                paddingAngle={2}
                stroke="var(--color-surface)"
                strokeWidth={0}
              >
                {items.map((item, index) => (
                  <Cell
                    fill={chartColors[index % chartColors.length]}
                    fillOpacity={(hasSelection ? selectedLabels.includes(item.label) : activeIndex === null || index === activeIndex) ? 1 : 0.45}
                    key={item.label}
                  />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          {hasSelection && onClear ? (
            <button className="donut-chart__center donut-chart__center--clear" type="button"
              aria-label={`Clear payer filter`} onClick={onClear}>
              <strong>{(activeItem?.value ?? total).toLocaleString()}</strong>
              <span>{selectionLabel}</span>
            </button>
          ) : (
            <div className="donut-chart__center" aria-hidden="true">
              <strong>{(centerMode === 'total' ? total : activeItem?.value ?? total).toLocaleString()}</strong>
              <span>{centerMode === 'total' ? 'Total' : activeItem?.label ?? 'Total'}</span>
            </div>
          )}
        </div>
        <table className="donut-chart__legend" onMouseLeave={() => setActiveIndex(null)}>
          <caption className="visually-hidden">{title} breakdown</caption>
          <thead className="visually-hidden">
            <tr>
              <th scope="col">Payer type</th>
              <th scope="col">{valueLabel}</th>
              <th scope="col">Share</th>
            </tr>
          </thead>
          <tbody>
          {items.map((item, index) => (
            <tr
              className={index === activeIndex ? 'donut-chart__legend-item--active' : undefined}
              key={item.label}
              onBlur={() => setActiveIndex(null)}
              onMouseEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              onClick={onSelect ? () => onSelect(item.label) : undefined}
              style={onSelect ? { cursor: 'pointer' } : undefined}
              tabIndex={onSelect ? undefined : 0}
            >
              <td className="donut-chart__legend-label">
                <span
                  className="donut-chart__legend-marker"
                  style={{ backgroundColor: chartColors[index % chartColors.length] }}
                />
                {onSelect ? <button type="button" className="donut-chart__legend-select"
                  aria-pressed={onClear ? selectedLabels.includes(item.label) : undefined} onClick={(event) => { event.stopPropagation(); onSelect(item.label) }}>
                  {item.label}
                </button> : item.label}
              </td>
              <td>{item.value.toLocaleString()}</td>
              <td>{total === 0 ? 0 : Math.round((item.value / total) * 100)}%</td>
            </tr>
          ))}
          </tbody>
        </table>
      </div>}
      <table className="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Payer type</th>
            <th scope="col">{valueLabel}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td>{item.value.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
