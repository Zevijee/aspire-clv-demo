import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FilterDropdown } from '../../../shared/components/filters/FilterDropdown'
import { getAdmissionsFilterOptions } from '../api/admissions'

export function ReferringFacilityFilter() {
  const [params, setParams] = useSearchParams()
  const [retry, setRetry] = useState(0)
  const [result, setResult] = useState<{ retry: number; facilities?: string[]; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getAdmissionsFilterOptions().then(
      data => { if (active) setResult({ retry, facilities: data.facilities }) },
      () => { if (active) setResult({ retry, error: 'Facilities could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [retry])
  const current = result?.retry === retry ? result : null
  return <FilterDropdown label="Facilities" placeholder="All facilities"
    options={(current?.facilities ?? []).map(value => ({ value, label: value }))}
    values={params.getAll('referring_facility')} loading={!current} error={current?.error}
    onRetry={() => setRetry(value => value + 1)}
    onChange={values => {
      const next = new URLSearchParams(params)
      next.delete('referring_facility')
      values.forEach(value => next.append('referring_facility', value))
      setParams(next)
    }} />
}
