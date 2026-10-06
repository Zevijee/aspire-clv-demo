/** The state -> portfolio -> region -> facility drilldown both Current Medicare
 * PDPM tabs use: facility rows grouped at the level below the current path,
 * each group keeping its facilities so any measure can be summed for it. */
export type Located = { facility_id: string; facility_name: string; state: string; portfolio: string; region: string }
export type DrilldownRow<Item> = { key: string; name: string; path: string[]; facilities: Item[]; isTotal?: boolean }

export const drilldownLevels = ['State', 'Portfolio', 'Region', 'Facility']

export function locationPath(item: Located) {
  return [item.state, item.portfolio, item.region, item.facility_name]
}

export function groupByLocation<Item extends Located>(items: Item[], path: string[]) {
  const depth = Math.min(path.length, 3)
  const groups = new Map<string, DrilldownRow<Item>>()
  for (const item of items) {
    const parts = locationPath(item)
    if (!path.every((value, index) => parts[index] === value)) continue
    const nextPath = parts.slice(0, depth + 1)
    const key = JSON.stringify(nextPath)
    const row = groups.get(key) ?? { key, name: parts[depth], path: nextPath, facilities: [] }
    row.facilities.push(item)
    groups.set(key, row)
  }
  return { depth, rows: [...groups.values()] }
}

/** One row per facility, for the Show all facilities view. */
export function facilityRows<Item extends Located>(items: Item[]): DrilldownRow<Item>[] {
  return items.map(item => ({ key: item.facility_id, name: item.facility_name, path: locationPath(item), facilities: [item] }))
}
