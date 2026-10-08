import { groupLocations, type CustomGrouping } from '../../../shared/customGrouping'

/** The state -> portfolio -> region -> facility drilldown both Current Medicare
 * PDPM tabs use: facility rows grouped at the level below the current path,
 * each group keeping its facilities so any measure can be summed for it. */
export type Located = { facility_id: string; facility_name: string; state: string; portfolio: string; region: string }
export type DrilldownRow<Item> = { key: string; name: string; path: string[]; facilities: Item[]; isTotal?: boolean }

export const drilldownLevels = ['State', 'Portfolio', 'Region', 'Facility']

export function locationPath(item: Located) {
  return [item.state, item.portfolio, item.region, item.facility_name]
}

export function groupByLocation<Item extends Located>(items: Item[], path: string[], grouping: CustomGrouping | null) {
  return groupLocations(items, path, grouping)
}

/** One row per facility, for the Show all facilities view. */
export function facilityRows<Item extends Located>(items: Item[]): DrilldownRow<Item>[] {
  return items.map(item => ({ key: item.facility_id, name: item.facility_name, path: locationPath(item), facilities: [item] }))
}
