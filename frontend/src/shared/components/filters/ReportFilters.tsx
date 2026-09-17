import type { ReactNode } from 'react'

type ReportFiltersProps = {
  children: ReactNode
}

export function ReportFilters({ children }: ReportFiltersProps) {
  return <div className="report-filters">{children}</div>
}
