import type { ReactNode } from 'react'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { locationLevels, useLocationView } from '../../../shared/customGrouping'
import { drilldownLevels as levels } from '../utils/locationDrilldown'

/** The drilldown bar the MDS reports share: breadcrumbs along one location
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
