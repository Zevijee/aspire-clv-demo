import type { ReportDefinition } from '../../shared/types/report'

export const adtReports: ReportDefinition[] = [
  {
    description: 'Review admissions activity across facilities.',
    module: 'ADT',
    path: '/adt/admissions',
    title: 'Admissions',
  },
  {
    description: 'Review resident discharge activity across facilities.',
    module: 'ADT',
    path: '/adt/discharges',
    title: 'Discharges',
  },
  {
    description: 'Review payer changes across the portfolio.',
    module: 'ADT',
    path: '/adt/payer-changes',
    title: 'Payer Changes',
  },
  {
    description: 'Review net resident movement from admissions and discharges.',
    module: 'ADT',
    path: '/adt/net-change',
    title: 'Net Change',
  },
  {
    description: 'Review month-over-month admissions, discharges, and net movement.',
    module: 'ADT',
    path: '/adt/monthly-trending',
    title: 'Monthly ADT Trending',
  },
  {
    description: 'Review referral activity by originating hospital.',
    module: 'ADT',
    path: '/adt/referring-hospital',
    title: 'Referring Hospital',
  },
]
