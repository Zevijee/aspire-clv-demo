import type { ReportDefinition } from '../../shared/types/report'

export const mdsReports: ReportDefinition[] = [
  {
    description: 'Review the current Medicare skilled nursing facility resident census and assessment status.',
    module: 'MDS',
    path: '/mds/current-medicare',
    title: 'Current Medicare',
  },
  {
    description: 'Review historical Medicare resident, assessment, and reimbursement trends.',
    module: 'MDS',
    path: '/mds/historical-medicare',
    title: 'Historical Medicare',
  },
  {
    description: 'Review the current Medicaid resident census and assessment status.',
    module: 'MDS',
    path: '/mds/current-medicaid',
    title: 'Current Medicaid',
  },
  {
    description: 'Review historical Medicaid resident and assessment trends.',
    module: 'MDS',
    path: '/mds/historical-medicaid',
    title: 'Historical Medicaid',
  },
  {
    description: 'Calculate the Patient-Driven Payment Model classification and projected daily rate.',
    module: 'MDS',
    path: '/mds/pdpm-calculator',
    title: 'PDPM Calculator',
  },
]
