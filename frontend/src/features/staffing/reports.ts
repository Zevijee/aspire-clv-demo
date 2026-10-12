import type { ReportDefinition } from '../../shared/types/report'

// The Staffing module's reports.
export const staffingReports: ReportDefinition[] = [
  {
    description: 'Review nursing hours per patient day.',
    module: 'Staffing',
    path: '/staffing/ppd',
    title: 'PPD',
  },
  {
    description: 'Compare agency and in-house staffing.',
    module: 'Staffing',
    path: '/staffing/agency-vs-inhouse',
    title: 'Agency vs In-house',
  },
  {
    description: 'Review hours over 40 a week per person, and what they cost.',
    module: 'Staffing',
    path: '/staffing/overtime',
    title: 'Overtime',
  },
]
