import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { AdmissionsPayerFilter } from '../../adt/components/AdmissionsPayerFilter'
import { TRANSFER_REASONS } from '../api'

// The URL parameters the donuts and these dropdowns share.
export const TRANSFER_PAYER_PARAM = 'transfer_payer'
export const TRANSFER_REASON_PARAM = 'transfer_reason'

/** Hospital Transfers' header filters, beside the date range: the same payer
 * and reason filters its donuts set, kept in the URL, so either one changes the
 * other. */
export function TransferFilters() {
  const [params, setParams] = useReportSearchParams()
  const set = (param: string) => (values: string[]) => {
    const next = new URLSearchParams(params)
    next.delete(param)
    values.forEach(value => next.append(param, value))
    setParams(next)
  }
  return <>
    <AdmissionsPayerFilter values={params.getAll(TRANSFER_PAYER_PARAM)} onChange={set(TRANSFER_PAYER_PARAM)} />
    <FilterDropdown label="Reasons" placeholder="All reasons"
      options={TRANSFER_REASONS.map(reason => ({ value: reason, label: reason }))}
      values={params.getAll(TRANSFER_REASON_PARAM)} onChange={set(TRANSFER_REASON_PARAM)} />
  </>
}
