export type AnalyticsModule = 'ADT' | 'Census' | 'MDS'

export type ReportDefinition = {
  description: string
  module: AnalyticsModule
  path: string
  title: string
}
