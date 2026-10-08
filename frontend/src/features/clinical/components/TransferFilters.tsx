import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useSearchParamList } from '../../../shared/hooks/useSearchParamList'
import { AdmissionsPayerFilter } from '../../adt/components/AdmissionsPayerFilter'
import { TRANSFER_REASONS } from '../api'

// The URL parameters the donuts and these dropdowns share.
export const TRANSFER_PAYER_PARAM = 'transfer_payer'
export const TRANSFER_REASON_PARAM = 'transfer_reason'

/** Hospital Transfers' header filters, beside the date range: the same payer
 * and reason filters its donuts set, kept in the URL, so either one changes the
 * other. */
export function TransferFilters() {
  const payers = useSearchParamList(TRANSFER_PAYER_PARAM)
  const reasons = useSearchParamList(TRANSFER_REASON_PARAM)
  return <>
    <AdmissionsPayerFilter values={payers.values} onChange={payers.set} />
    <FilterDropdown label="Reasons" placeholder="All reasons"
      options={TRANSFER_REASONS.map(reason => ({ value: reason, label: reason }))}
      values={reasons.values} onChange={reasons.set} />
  </>
}
