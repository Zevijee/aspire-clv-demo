import type { AdmissionsMetricFilters } from '../api/admissions'
import { AdmissionsKpis } from './AdmissionsKpis'
import { AdmissionsDailyTrend } from './AdmissionsDailyTrend'
import { AdmissionsReadmissionsDistribution } from './AdmissionsReadmissionsDistribution'
import { AdmissionsSourceTypeDistribution } from './AdmissionsSourceTypeDistribution'

type AdmissionsOverallProps = {
  filters: AdmissionsMetricFilters
}

export function AdmissionsOverall({ filters }: AdmissionsOverallProps) {
  return (
    <>
      <AdmissionsKpis filters={filters} />
      <div className="admissions-dashboard">
        <AdmissionsSourceTypeDistribution filters={filters} />
        <AdmissionsReadmissionsDistribution filters={filters} />
      </div>
      <AdmissionsDailyTrend filters={filters} />
    </>
  )
}
