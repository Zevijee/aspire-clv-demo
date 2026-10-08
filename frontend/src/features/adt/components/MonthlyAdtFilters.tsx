import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { monthlyFilter } from '../api/monthlyAdt'
import { PayerFilter } from './PayerFilter'

/** Monthly ADT Trending's filters: payers, and where residents came from and
 * went to -- each narrowing only its own view's numbers. With a view, only that
 * view's filter; without one, both. Shared by the report header and its modals. */
export function MonthlyAdtFilters({ activeTab }: { activeTab?: string }) {
  const [params, setParams] = useReportSearchParams()
  const setAll = (key: string, values: string[]) => {
    const next = new URLSearchParams(params)
    next.delete(key)
    values.forEach(value => next.append(key, value))
    setParams(next)
  }
  const filters = activeTab === undefined ? Object.values(monthlyFilter)
    : activeTab in monthlyFilter ? [monthlyFilter[activeTab as keyof typeof monthlyFilter]] : []
  return <>
    <PayerFilter values={params.getAll('monthly_payer')} onChange={payers => setAll('monthly_payer', payers)} />
    {/* Net change reads census, which does not divide by where a resident came from or went to. */}
    {filters.map(filter => <FilterDropdown key={filter.search} label={filter.label} placeholder={filter.placeholder}
      options={filter.options.map(value => ({ value, label: value }))}
      values={params.getAll(filter.search)} onChange={values => setAll(filter.search, values)} />)}
  </>
}
