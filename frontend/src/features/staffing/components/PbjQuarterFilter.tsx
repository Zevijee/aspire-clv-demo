import { useSearchParams } from 'react-router-dom'
import { FilterSelect } from '../../../shared/components/filters/FilterSelect'
import { PBJ_QUARTER_PARAM, pbjQuarters, selectedPbjQuarter } from '../pbjQuarters'

/** PBJ Compliance's header control in place of a date range: one CMS fiscal
 * quarter, as PBJ is submitted, kept in the URL. */
export function PbjQuarterFilter() {
  const [params, setParams] = useSearchParams()
  const selected = selectedPbjQuarter(params)
  return <FilterSelect label="PBJ quarter" value={selected.value}
    options={pbjQuarters().map(entry => ({ value: entry.value, label: entry.label }))}
    onChange={value => {
      const next = new URLSearchParams(params)
      next.set(PBJ_QUARTER_PARAM, value)
      setParams(next)
    }} />
}
