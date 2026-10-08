import type { ReactNode } from 'react'
import { ReportHeaderFilters } from '../../activeFilters'

type ReportFiltersProps = {
  children: ReactNode
}

export function ReportFilters({ children }: ReportFiltersProps) {
  return <div className="report-filters"><ReportHeaderFilters>{children}</ReportHeaderFilters></div>
}
