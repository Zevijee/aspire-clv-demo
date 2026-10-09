export type AnalyticsModule = 'ADT' | 'Census' | 'MDS' | 'Clinical' | 'Staffing'

export type ReportDefinition = {
  description: string
  module: AnalyticsModule
  path: string
  title: string
}
