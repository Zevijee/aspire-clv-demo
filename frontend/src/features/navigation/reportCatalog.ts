import { adtReports } from '../adt/reports'
import { censusReports } from '../census/reports'
import { mdsReports } from '../mds/reports'
import type { AnalyticsModule, ReportDefinition } from '../../shared/types/report'

export const analyticsModules: AnalyticsModule[] = ['ADT', 'Census', 'MDS']

export const reports = [...adtReports, ...censusReports, ...mdsReports]

export const reportsByModule = Object.fromEntries(
  analyticsModules.map((module) => [module, reports.filter((report) => report.module === module)]),
) as Record<AnalyticsModule, ReportDefinition[]>
