import type { ReportDefinition } from '../../shared/types/report'

export const censusReports: ReportDefinition[] = [
  {
    description: 'Review current facility census by day.',
    module: 'Census',
    path: '/census/daily-census',
    title: 'Live Census',
  },
  {
    description: 'Review census performance across the portfolio.',
    module: 'Census',
    path: '/census/overview',
    title: 'Census Overview',
  },
  {
    description: 'Review the current resident population by facility.',
    module: 'Census',
    path: '/census/residents',
    title: 'Residents',
  },
  {
    description: 'Review current bed availability and occupancy by facility.',
    module: 'Census',
    path: '/census/bed-board',
    title: 'Bed Board',
  },
  {
    description: 'Review day-by-day census performance across facilities.',
    module: 'Census',
    path: '/census/daily-trending',
    title: 'Daily Census Trending',
  },
  {
    description: 'Review month-over-month census performance across facilities.',
    module: 'Census',
    path: '/census/monthly-trending',
    title: 'Monthly Census Trending',
  },
]
