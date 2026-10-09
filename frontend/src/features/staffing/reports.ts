import type { ReportDefinition } from '../../shared/types/report'

// The Staffing module's reports.
export const staffingReports: ReportDefinition[] = [
  {
    description: 'Review nursing hours per patient day.',
    module: 'Staffing',
    path: '/staffing/ppd',
    title: 'PPD',
  },
]
