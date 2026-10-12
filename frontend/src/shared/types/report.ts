export type AnalyticsModule = 'ADT' | 'Census' | 'PDPM' | 'Clinical' | 'Staffing'

export type ReportDefinition = {
  description: string
  module: AnalyticsModule
  path: string
  title: string
}
