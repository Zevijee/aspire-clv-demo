import type { ReactNode } from 'react'
import { DrilldownNavigation } from './DrilldownNavigation'
import { locationLevels, useLocationView } from '../customGrouping'
import { drilldownLevels as levels, type DrilldownRow } from '../utils/locationDrilldown'
import type { TableColumn } from './Table'

/** The drilldown bar the location reports share: breadcrumbs along one location
 * path, the level it is at, and any controls the report puts beside them. */
export function LocationNavigation({ path, setPath, controls }: {
  path: string[]; setPath: (path: string[]) => void; controls?: ReactNode
}) {
  const { grouping, locationView } = useLocationView(() => setPath([]))
  const depth = path.length ? Math.min(path.length, 3) : grouping ? locationLevels.indexOf(grouping.level) : 0
  return <DrilldownNavigation locationView={locationView} items={path.map((name, index) => ({ id: JSON.stringify(path.slice(0, index + 1)), label: name,
    onSelect: () => setPath(path.slice(0, index + 1)) }))}
    level={{ current: depth + 1, total: 4, label: levels[depth] }} controls={controls} />
}

/** The location column every browser-side drilldown starts with: the level's
 * name, a link down a level until the facility. */
export function locationColumn<Item>(depth: number, path: string[], setPath: (path: string[]) => void):
    TableColumn<DrilldownRow<Item>> {
  return { id: 'name', header: levels[depth], isRowHeader: true, value: row => row.name,
    format: (_, row) => row.isTotal || path.length === 4 ? row.name :
      <button type="button" className="drilldown-table__link" onClick={() => setPath(row.path)}>{row.name}</button> }
}
