import type { ReportDefinition } from '../../shared/types/report'

export const mdsReports: ReportDefinition[] = [
  {
    description: 'Review the current Medicare skilled nursing facility resident census and assessment status.',
    module: 'MDS',
    path: '/mds/current-medicare',
    title: 'Current Medicare PDPM',
  },
  {
    description: 'Review Medicare PDPM stays in a date range: length of stay and actual against neutral rates and revenue.',
    module: 'MDS',
    path: '/mds/historical-medicare',
    title: 'Historical Medicare PDPM',
  },
  {
    description: 'Review Medicare PDPM residents and rates month by month.',
    module: 'MDS',
    path: '/mds/monthly-medicare',
    title: 'Monthly Medicare PDPM Trending',
  },
  {
    description: 'Work through a resident\'s PDPM classification.',
    module: 'MDS',
    path: '/mds/pdpm-worksheet',
    title: 'PDPM Worksheet',
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
