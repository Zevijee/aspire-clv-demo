import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

/** A report filter that has something selected, and how to clear it. */
export type ActiveFilter = { name: string; clear: () => void }

type Announcement = { name: string; active: boolean; clear: () => void }

// Two contexts: registering is stable, so a filter that announces itself does
// not re-run when the list changes; the list is what the drilldown bar reads.
const RegisterContext = createContext<((owner: symbol, filters: ActiveFilter[]) => void) | null>(null)
const FiltersContext = createContext<ActiveFilter[]>([])
// Set by the report header's filter area, so a dropdown there is a report
// filter, while the same dropdown in a table's column header is not.
const HeaderContext = createContext(false)

/** One name per filter however it is labelled: "Payers" on the header
 * dropdown and "payer" on the donut are the same filter. */
function normalize(name: string) {
  const lower = name.trim().toLowerCase()
  if (lower.endsWith('ies')) return `${lower.slice(0, -3)}y`
  if (lower.endsWith('s') && !lower.endsWith('ss')) return lower.slice(0, -1)
  return lower
}

/** Holds the active filters of one report view. ReportLayout gives every report
 * one, and FullScreenModal gives each modal its own, so a modal's filters never
 * show in the page's bar. */
export function ActiveFiltersProvider({ children }: { children: ReactNode }) {
  const [owners, setOwners] = useState(new Map<symbol, ActiveFilter[]>())
  const register = useCallback((owner: symbol, filters: ActiveFilter[]) => setOwners(current => {
    if (!filters.length && !current.has(owner)) return current
    const next = new Map(current)
    if (filters.length) next.set(owner, filters)
    else next.delete(owner)
    return next
  }), [])
  // Once each: the header dropdown and the chart showing the same selection
  // are one filter, and clearing either clears it.
  const filters = useMemo(() => {
    const byName = new Map<string, ActiveFilter>()
    for (const list of owners.values()) {
      for (const filter of list) if (!byName.has(filter.name)) byName.set(filter.name, filter)
    }
    return [...byName.values()]
  }, [owners])
  return <RegisterContext.Provider value={register}>
    <FiltersContext.Provider value={filters}>{children}</FiltersContext.Provider>
  </RegisterContext.Provider>
}

/** Marks the report header's filter area; see HeaderContext. */
export function ReportHeaderFilters({ children }: { children: ReactNode }) {
  return <HeaderContext.Provider value={true}>{children}</HeaderContext.Provider>
}

export const useInReportHeader = () => useContext(HeaderContext)

/** The active filters of this view, for the drilldown bar. */
export const useActiveFilters = () => useContext(FiltersContext)

/** Announce a shared control's filters to its view. The shared filter controls
 * call this themselves -- header dropdowns, the side-filter drawer, chart
 * selections -- so a report never wires its filters to the bar. */
export function useAnnounceFilters(announcements: Announcement[]) {
  const register = useContext(RegisterContext)
  const owner = useRef(Symbol('filters')).current
  // The latest clear functions, so a new closure each render does not re-register.
  const clears = useRef(announcements.map(item => item.clear))
  clears.current = announcements.map(item => item.clear)
  const key = JSON.stringify(announcements.map(item => [normalize(item.name), item.active]))
  useEffect(() => {
    if (!register) return
    const active = (JSON.parse(key) as [string, boolean][])
      .map(([name, on], index) => on ? { name, clear: () => clears.current[index]?.() } : null)
      .filter((filter): filter is ActiveFilter => filter !== null)
    register(owner, active)
  }, [register, owner, key])
  useEffect(() => () => register?.(owner, []), [register, owner])
}
