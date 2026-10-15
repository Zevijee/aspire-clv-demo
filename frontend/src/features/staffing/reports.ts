import type { ReportDefinition } from '../../shared/types/report'

// The Staffing module's reports, in the order of the Staffing Overview's sections.
export const staffingReports: ReportDefinition[] = [
  {
    description: 'Review hours against budget and what labour cost, by location.',
    module: 'Staffing',
    path: '/staffing/overview',
    title: 'Overview',
  },
  {
    description: 'Review hours worked per patient day.',
    module: 'Staffing',
    path: '/staffing/hppd',
    title: 'HPPD',
  },
  {
    description: 'Review labour cost per patient day.',
    module: 'Staffing',
    path: '/staffing/ppd',
    title: 'PPD cost',
  },
  {
    description: 'Review every kind of hour paid, by location and role.',
    module: 'Staffing',
    path: '/staffing/hours',
    title: 'Hours',
  },
  {
    description: 'Review what an hour of each kind paid.',
    module: 'Staffing',
    path: '/staffing/hourly-rate',
    title: 'Hourly rate',
  },
  {
    description: 'Review what each kind of hour cost.',
    module: 'Staffing',
    path: '/staffing/cost',
    title: 'Cost',
  },
  {
    description: 'Compare agency and in-house staffing.',
    module: 'Staffing',
    path: '/staffing/agency-vs-inhouse',
    title: 'Agency vs In-house',
  },
  {
    description: 'Review hours over 40 a week per employee, and what they cost.',
    module: 'Staffing',
    path: '/staffing/overtime',
    title: 'Overtime',
  },
  {
    description: 'Review excess spend over budget and the agency and overtime premiums.',
    module: 'Staffing',
    path: '/staffing/premiums-and-extras',
    title: 'Premiums and extras',
  },
  {
    description: 'Review orientation for new hires, how long it takes and what it costs.',
    module: 'Staffing',
    path: '/staffing/orientation',
    title: 'Orientation',
  },
  {
    description: 'Review in-service training hours and what they cost.',
    module: 'Staffing',
    path: '/staffing/training',
    title: 'Training',
  },
  {
    description: 'Review how many employees leave and stay, and how long they stay.',
    module: 'Staffing',
    path: '/staffing/turnover',
    title: 'Turnover and Retention',
  },
  {
    description: 'Check each PBJ quarter as CMS reads it: nurse hours, RN coverage, turnover and the deadline.',
    module: 'Staffing',
    path: '/staffing/pbj',
    title: 'PBJ Compliance',
  },
  {
    description: 'Review hours against budget and HPPD month by month.',
    module: 'Staffing',
    path: '/staffing/monthly-trending',
    title: 'Monthly Staffing Trending',
  },
]
