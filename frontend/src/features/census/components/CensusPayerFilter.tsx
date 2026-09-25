import { AdmissionsPayerFilter } from '../../adt/components/AdmissionsPayerFilter'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'

/** The Payers filter for a census report, kept in the page's search parameters
 * under `param`, so the report header and any modal over it share one filter. */
export function CensusPayerFilter({ param }: { param: string }) {
  const [params, setParams] = useReportSearchParams()
  return <AdmissionsPayerFilter values={params.getAll(param)} onChange={payers => {
    const next = new URLSearchParams(params)
    next.delete(param)
    payers.forEach(payer => next.append(param, payer))
    setParams(next)
  }} />
}
