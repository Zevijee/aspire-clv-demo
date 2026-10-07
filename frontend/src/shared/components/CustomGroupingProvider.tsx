import { useState, type ReactNode } from 'react'
import { CustomGroupingContext, loadGrouping, saveGrouping, type CustomGrouping } from '../customGrouping'

/** Holds the app's one custom grouping, so it follows the reader between
 * reports, and keeps it in the browser so it survives a reload. */
export function CustomGroupingProvider({ children }: { children: ReactNode }) {
  const [grouping, setState] = useState<CustomGrouping | null>(loadGrouping)
  const setGrouping = (next: CustomGrouping | null) => {
    const value = next?.locations.length ? next : null
    saveGrouping(value)
    setState(value)
  }
  return <CustomGroupingContext.Provider value={{ grouping, setGrouping }}>{children}</CustomGroupingContext.Provider>
}
