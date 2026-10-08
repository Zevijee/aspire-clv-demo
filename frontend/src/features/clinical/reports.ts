import type { ReportDefinition } from '../../shared/types/report'

// The Clinical module's reports.
export const clinicalReports: ReportDefinition[] = [
  {
    description: 'Review residents transferred from the facility to a hospital.',
    module: 'Clinical',
    path: '/clinical/hospital-transfers',
    title: 'Hospital Transfers',
  },
  {
    description: 'Review resident incidents.',
    module: 'Clinical',
    path: '/clinical/incidents',
    title: 'Incidents',
  },
]
