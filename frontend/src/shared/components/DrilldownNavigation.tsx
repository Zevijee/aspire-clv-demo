import { useEffect, useRef } from 'react'

export type DrilldownBreadcrumb = {
  id: string
  label: string
  onSelect?: () => void
}

type DrilldownNavigationProps = {
  ariaLabel?: string
  activeFilters?: readonly string[]
  onClearFilter?: (filter: string) => void
  clearAction?: { label: string; onClick: () => void }
  /** Builds the shared location-view root and reset action before the supplied path. */
  locationView?: {
    groupBy: 'state' | 'portfolio' | 'region' | 'facility'
    selectedCount: number
    selectionLevel?: 'state' | 'portfolio' | 'region' | 'facility'
    onReturn: () => void
    onClear: () => void
  }
  /** Ordered from the root to the current location; the final item is not clickable. */
  items: readonly DrilldownBreadcrumb[]
  level?: { current: number; total: number; label: string }
}

export function DrilldownNavigation({
  ariaLabel = 'Drill-down navigation',
  activeFilters = [],
  onClearFilter,
  clearAction: suppliedClearAction,
  items: pathItems,
  locationView,
  level,
}: DrilldownNavigationProps) {
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
      {activeFilters.length > 0 && (
        <>
          {onClearFilter && activeFilters.map((filter) => (
            <button key={filter} className="drilldown-navigation__clear" type="button"
              onClick={() => onClearFilter(filter)}>Clear {filter} filter</button>
          ))}
        </>
      )}
      {level && (
        <span className="drilldown-navigation__level">
          Level {level.current} of {level.total} · {level.label}
        </span>
      )}
      </div>
    </nav>
  )
}
