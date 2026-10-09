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
  {
    description: 'Review resident fevers and infections.',
    module: 'Clinical',
    path: '/clinical/fever-infections',
    title: 'Fever / Infections',
  },
  {
    description: 'Review resident weight changes.',
    module: 'Clinical',
    path: '/clinical/weight-surveillance',
    title: 'Weight Surveillance',
  },
  {
    description: 'Review progress notes flagged for follow-up.',
    module: 'Clinical',
    path: '/clinical/flagged-progress-notes',
    title: 'Flagged Progress Notes',
  },
]
