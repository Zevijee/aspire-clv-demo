import { createContext, useContext } from 'react'
import type { FacilityLocation } from '../features/adt/api/admissionsOverview'

/** One custom grouping for the whole app: a level and the locations chosen at
 * it. Every drilldown's top level then shows just those locations, each still
 * drillable, until it is cleared -- on any report, since it follows the reader
 * from report to report.
 *
 * A location is a JSON name path from state down, the format the ADT reports'
 * own location selection already uses: '["FL","Florida 1","Lakeland"]' is a
 * region. Names, not ids, because the client-side reports group facility rows
 * by name and the ADT reports resolve names to facility ids themselves. */
export type LocationLevel = 'state' | 'portfolio' | 'region' | 'facility'
export const locationLevels: readonly LocationLevel[] = ['state', 'portfolio', 'region', 'facility']
export const levelLabels: Record<LocationLevel, { one: string; many: string }> = {
  state: { one: 'State', many: 'States' }, portfolio: { one: 'Portfolio', many: 'Portfolios' },
  region: { one: 'Region', many: 'Regions' }, facility: { one: 'Facility', many: 'Facilities' },
}

export type CustomGrouping = { level: LocationLevel; locations: string[] }

type CustomGroupingState = {
  /** null when no custom grouping is set: drilldowns start at All states. */
  grouping: CustomGrouping | null
  setGrouping: (grouping: CustomGrouping | null) => void
}

export const CustomGroupingContext = createContext<CustomGroupingState>({ grouping: null, setGrouping: () => {} })

export function useCustomGrouping() {
  return useContext(CustomGroupingContext)
}

/** Each chosen location as its name path. */
export function groupingPaths(grouping: CustomGrouping | null): string[][] {
  return (grouping?.locations ?? []).map(location => JSON.parse(location) as string[])
}

const STORAGE_KEY = 'custom-grouping'

/** The saved grouping, if this browser kept one. Storage can be unavailable;
 * then the grouping lasts until the page is closed. */
export function loadGrouping(): CustomGrouping | null {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as CustomGrouping | null
    return saved && locationLevels.includes(saved.level) && Array.isArray(saved.locations) && saved.locations.length
      ? saved : null
  } catch {
    return null
  }
}

export function saveGrouping(grouping: CustomGrouping | null) {
  try {
    if (grouping) localStorage.setItem(STORAGE_KEY, JSON.stringify(grouping))
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* Keep the grouping in memory when storage is unavailable. */ }
}

/** The choices at one level: each location's name, with where it sits. */
export function locationOptions(locations: FacilityLocation[], level: LocationLevel) {
  const depth = locationLevels.indexOf(level)
  const options = new Map<string, { value: string; label: string; context: string }>()
  for (const location of locations) {
    const path = [location.state, location.portfolio_name, location.region_name, location.facility_name].slice(0, depth + 1)
    const value = JSON.stringify(path)
    options.set(value, { value, label: path[depth], context: path.slice(0, depth).join(' / ') })
  }
  return [...options.values()].sort((a, b) => a.label.localeCompare(b.label) || a.context.localeCompare(b.context))
}

/** Rows for a drilldown's current level, grouped from facility items, with
 * the custom grouping applied at the top: with no path, the chosen locations
 * are the rows; once drilled into one, grouping goes on from it as usual. */
export function groupLocations<Item extends { state: string; portfolio: string; region: string; facility_name: string }>(
    items: Item[], path: string[], grouping: CustomGrouping | null) {
  const place = (item: Item) => [item.state, item.portfolio, item.region, item.facility_name]
  const under = (item: Item, prefix: string[]) => prefix.every((part, index) => place(item)[index] === part)
  if (grouping && !path.length) {
    return { depth: locationLevels.indexOf(grouping.level), rows: groupingPaths(grouping).map(prefix => ({
      key: JSON.stringify(prefix), name: prefix[prefix.length - 1], path: prefix,
      facilities: items.filter(item => under(item, prefix)) })) }
  }
  const depth = Math.min(path.length, 3)
  const groups = new Map<string, { key: string; name: string; path: string[]; facilities: Item[] }>()
  for (const item of items) {
    if (!under(item, path)) continue
    const nextPath = place(item).slice(0, depth + 1)
    const key = JSON.stringify(nextPath)
    const row = groups.get(key) ?? { key, name: nextPath[depth], path: nextPath, facilities: [] }
    row.facilities.push(item)
    groups.set(key, row)
  }
  return { depth, rows: [...groups.values()] }
}

/** The drilldown bar's location view for the app-wide grouping: its root
 * crumb returns to the chosen locations, and clearing drops the grouping.
 * `reset` returns the report's own path to its top. */
export function useLocationView(reset: () => void) {
  const { grouping, setGrouping } = useCustomGrouping()
  return { grouping, locationView: {
    groupBy: grouping?.level ?? 'state' as LocationLevel,
    selectedCount: grouping?.locations.length ?? 0,
    onReturn: reset,
    onClear: () => { setGrouping(null); reset() },
  } }
}

/** Whether a facility, by its [state, portfolio, region, facility] names, is
 * in the drilldown's current view: under the path, or at the top under any
 * of the grouping's locations. */
export function inView(place: readonly string[], path: string[], grouping: CustomGrouping | null) {
  const under = (prefix: string[]) => prefix.every((part, index) => place[index] === part)
  return grouping && !path.length ? groupingPaths(grouping).some(under) : under(path)
}
