import { useActiveFilters } from '../activeFilters'
import { locationLevels, type LocationLevel } from '../customGrouping'
import { useEffect, useRef, type ReactNode } from 'react'

export type DrilldownBreadcrumb = {
  id: string
  label: string
  onSelect?: () => void
}

type DrilldownNavigationProps = {
  ariaLabel?: string
  clearAction?: { label: string; onClick: () => void }
  /** Builds the shared location-view root and reset action before the supplied
   * path. useLocationView supplies it from the app-wide grouping. */
  locationView?: {
    groupBy: 'state' | 'portfolio' | 'region' | 'facility'
    selectedCount: number
    selectionLevel?: 'state' | 'portfolio' | 'region' | 'facility'
    onReturn: () => void
    onClear: () => void
  }
  /** Ordered from the root to the current location; the final item is not clickable. */
  items: readonly DrilldownBreadcrumb[]
  /** Where the drilldown is: "Level 2 of 4 · Portfolio". Required, so every
   * location drilldown shows it; `locationLevel` builds it from a level name. */
  level: { current: number; total: number; label: string }
  /** The report's own controls, such as a category choice, on a row of their own
   * under the breadcrumbs. The bar is sticky, so they stay in reach on scroll. */
  controls?: ReactNode
}

export function DrilldownNavigation({
  ariaLabel = 'Drill-down navigation',
  clearAction: suppliedClearAction,
  items: pathItems,
  locationView,
  level,
  controls,
}: DrilldownNavigationProps) {
  const activeFilters = useActiveFilters()
  const isCustomView = Boolean(locationView && (locationView.groupBy !== 'state' || locationView.selectedCount > 0))
  let items = pathItems
  let clearAction = suppliedClearAction
  if (locationView) {
    const { groupBy, selectedCount, onReturn, onClear } = locationView
    const unit = locationView.selectionLevel ?? groupBy
    const plural = unit === 'facility' ? 'facilities' : `${unit}s`
    const selectionLabel = selectedCount
      ? `${selectedCount.toLocaleString()} ${selectedCount === 1 ? unit : plural} selected`
      : `All ${plural}`
    const viewLabel = `Custom ${groupBy === 'region' ? 'regional' : groupBy} view`
    items = [isCustomView
      ? { id: 'custom-selection', label: `${viewLabel} / ${selectionLabel}`, onSelect: onReturn }
      : { id: 'all-states', label: 'All states', onSelect: onClear }, ...pathItems]
    clearAction = isCustomView ? { label: 'Clear and return to All states', onClick: onClear } : undefined
  }
  const navigationRef = useRef<HTMLElement>(null)
  const pathKey = JSON.stringify(items.map((item) => item.id))
  const previousPathRef = useRef(pathKey)

  useEffect(() => {
    if (previousPathRef.current === pathKey) return
    previousPathRef.current = pathKey
    // Restore focus after the previous drill-down row or breadcrumb is removed.
    navigationRef.current?.focus({ preventScroll: true })
    navigationRef.current?.scrollIntoView({ block: 'nearest' })
  }, [pathKey])

  return (
    <nav aria-label={ariaLabel} className="drilldown-navigation" ref={navigationRef} tabIndex={-1}>
      <ol className="drilldown-navigation__breadcrumbs">
        {items.map((item, index) => {
          const current = index === items.length - 1
          return (
            <li key={item.id}>
              {index > 0 && (
                <svg aria-hidden="true" fill="none" viewBox="0 0 16 16">
                  <path d="m6 3 5 5-5 5" />
                </svg>
              )}
              {current || !item.onSelect ? (
                <span aria-current={current ? 'page' : undefined}>{item.label}</span>
              ) : (
                <button onClick={item.onSelect} type="button">{item.label}</button>
              )}
            </li>
          )
        })}
      </ol>
      <div className="drilldown-navigation__status">
      {clearAction && (
        <button className="drilldown-navigation__clear" type="button" onClick={clearAction.onClick}>
          {clearAction.label}
        </button>
      )}
      {/* Every active report filter, announced by the shared control that holds
          it: header dropdowns, the side-filter drawer, chart selections. */}
      {activeFilters.map((filter) => (
        <button key={filter.name} className="drilldown-navigation__clear" type="button"
          onClick={filter.clear}>Clear {filter.name} filter</button>
      ))}
      {level && (
        <span className="drilldown-navigation__level">
          Level {level.current} of {level.total} · {level.label}
        </span>
      )}
      </div>
      {controls && <div className="drilldown-navigation__controls">{controls}</div>}
    </nav>
  )
}

/** The bar's level for a location level name. */
export function locationLevel(level: LocationLevel) {
  return { current: locationLevels.indexOf(level) + 1, total: locationLevels.length,
    label: level[0].toUpperCase() + level.slice(1) }
}
