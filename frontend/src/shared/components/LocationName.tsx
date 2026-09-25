import type { ReactNode } from 'react'

/** A facility's name with its state, as in "Maple Grove Rehabilitation · TX",
 * so tables need not spend columns on the hierarchy. Hovering shows just its
 * portfolio and region, one per line, in the same browser tooltip
 * that shortened table cells use. State, portfolio and region stay filterable
 * from the table header. */
export function LocationName({ children, region, portfolio, state }: {
  children: ReactNode
  region?: string | null; portfolio?: string | null; state?: string | null
}) {
  const hover = `Portfolio: ${portfolio ?? '—'}\nRegion: ${region ?? '—'}`
  return <span className="location-name" title={hover}>{children}{state ? ` · ${state}` : ''}</span>
}
