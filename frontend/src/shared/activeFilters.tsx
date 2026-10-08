import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

/** A report filter that has something selected, and how to clear it. */
export type ActiveFilter = { name: string; clear: () => void }

// Where a filter is set: the report header, the side-filter drawer, or a chart.
type FilterKind = 'header' | 'drawer' | 'chart'
type Announcement = { name: string; active: boolean; clear: () => void; kind: FilterKind }
type Registered = ActiveFilter & { active: boolean; kind: FilterKind }

// Two contexts: registering is stable, so a filter that announces itself does
// not re-run when the list changes; the list is what the drilldown bar reads.
const RegisterContext = createContext<((owner: symbol, filters: Registered[]) => void) | null>(null)
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
 * show in the page's bar. `requireHeader` checks the header rule below; a modal
 * has no report header, so only the report page asks for it. */
export function ActiveFiltersProvider({ children, requireHeader = false }: {
  children: ReactNode; requireHeader?: boolean
}) {
  const [owners, setOwners] = useState(new Map<symbol, Registered[]>())
  const register = useCallback((owner: symbol, filters: Registered[]) => setOwners(current => {
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
      for (const filter of list) if (filter.active && !byName.has(filter.name)) byName.set(filter.name, filter)
    }
    return [...byName.values()]
  }, [owners])
  // The rule: a chart that filters the report has the same filter in the
  // header, beside the date range. A chart filter without one is reported as an
  // error, which the browser audit (tools/site_audit.py) fails on. Checked a
  // moment after the filters last changed: header and charts register in the
  // same render, and the audit reads errors half a second after loading ends.
  useEffect(() => {
    if (!requireHeader) return
    const timer = window.setTimeout(() => {
      const all = [...owners.values()].flat()
      const elsewhere = new Set(all.filter(filter => filter.kind !== 'chart').map(filter => filter.name))
      for (const name of new Set(all.filter(filter => filter.kind === 'chart').map(filter => filter.name))) {
        if (!elsewhere.has(name)) console.error(`The "${name}" chart filter has no header filter. Every filter `
          + 'a chart sets must also be a dropdown beside the date range; see "Report filters" in STYLE_GUIDE.md.')
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [owners, requireHeader])
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
  const key = JSON.stringify(announcements.map(item => [normalize(item.name), item.active, item.kind]))
  useEffect(() => {
    if (!register) return
    // Every filter, set or not: the bar lists the active ones, and the header
    // rule needs to know a filter exists before anything is chosen in it.
    register(owner, (JSON.parse(key) as [string, boolean, FilterKind][]).map(([name, active, kind], index) =>
      ({ name, active, kind, clear: () => clears.current[index]?.() })))
  }, [register, owner, key])
  useEffect(() => () => register?.(owner, []), [register, owner])
}
