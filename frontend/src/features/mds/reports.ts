import type { ReportDefinition } from '../../shared/types/report'

export const mdsReports: ReportDefinition[] = [
  {
    description: 'Review the current Medicare skilled nursing facility resident census and assessment status.',
    module: 'PDPM',
    path: '/mds/current-medicare',
    title: 'Current Medicare',
  },
  {
    description: 'Review Medicare PDPM stays in a date range: length of stay and actual against neutral rates and revenue.',
    module: 'PDPM',
    path: '/mds/historical-medicare',
    title: 'Historical Medicare',
  },
  {
    description: 'Review Medicare PDPM residents and rates month by month.',
    module: 'PDPM',
    path: '/mds/monthly-medicare',
    title: 'Monthly Medicare Trending',
  },
  {
    description: 'Work through a Medicare resident\'s PDPM classification.',
    module: 'PDPM',
    path: '/mds/pdpm-worksheet',
    title: 'Medicare Worksheet',
  },
  {
    description: 'Review the current Texas Medicaid PDPM residents and assessment status.',
    module: 'PDPM',
    path: '/mds/current-medicaid',
    title: 'Current Medicaid',
  },
  {
    description: 'Review Texas Medicaid PDPM stays in a date range: length of stay, census, rate and revenue.',
    module: 'PDPM',
    path: '/mds/historical-medicaid',
    title: 'Historical Medicaid',
  },
  {
    description: 'Compare Texas Medicaid PDPM census, rate and revenue month by month.',
    module: 'PDPM',
    path: '/mds/monthly-medicaid',
    title: 'Monthly Medicaid Trending',
  },
  {
    description: 'Work through a Texas Medicaid resident\'s PDPM nursing and NTA classification.',
    module: 'PDPM',
    path: '/mds/medicaid-pdpm-worksheet',
    title: 'Medicaid Worksheet',
  },
  {
    description: 'Calculate the Patient-Driven Payment Model classification and projected daily rate.',
    module: 'PDPM',
    path: '/mds/pdpm-calculator',
    title: 'Medicare Calculator',
  },
  {
    description: 'Price a Texas Medicaid case-mix code at a facility, a day and over a month.',
    module: 'PDPM',
    path: '/mds/medicaid-calculator',
    title: 'Medicaid Calculator',
  },
]
