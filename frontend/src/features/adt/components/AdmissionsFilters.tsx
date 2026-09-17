import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import { TabFilterBar, type TabFilterBarFilter } from '../../../shared/components/filters/TabFilterBar'
import {
  getAdmissionsFilterOptions,
  type AdmissionsFilterOptions,
  type AdmissionsMetricFilters,
} from '../api/admissions'

type AdmissionsFiltersProps = {
  filters: AdmissionsMetricFilters
  setFilters: Dispatch<SetStateAction<AdmissionsMetricFilters>>
}

export function AdmissionsFilters({ filters, setFilters }: AdmissionsFiltersProps) {
  const [filterOptions, setFilterOptions] = useState<AdmissionsFilterOptions | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [requestVersion, setRequestVersion] = useState(0)

  const retryOptions = useCallback(() => {
    setIsLoading(true)
    setError(null)
    setRequestVersion((current) => current + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    void getAdmissionsFilterOptions()
      .then((options) => {
        if (!cancelled) {
          setFilterOptions(options)
          setIsLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Filter options could not be loaded. Please try again.')
          setIsLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [requestVersion])

  const filterBarFilters = useMemo<TabFilterBarFilter[]>(
    () => [
      {
        id: 'payer',
        label: 'Payer',
        onChange: (payerTypes) => setFilters((current) => ({ ...current, payerTypes })),
        options: [
          { label: 'Medicare', value: 'Medicare' },
          { label: 'Commercial Medicare', value: 'Medicare Advantage' },
          { label: 'Medicare HMO', value: 'Medicare HMO' },
          { label: 'Managed Medicaid', value: 'Managed Medicaid' },
          { label: 'Medicaid', value: 'Medicaid' },
          { label: 'Hospice', value: 'Hospice' },
          { label: 'Private Pay', value: 'Private Pay' },
        ],
        values: filters.payerTypes,
      },
      {
        id: 'portfolio',
        label: 'Portfolio',
        isLoading,
        error,
        onRetry: retryOptions,
        onChange: (portfolios) => setFilters((current) => ({ ...current, portfolios })),
        options: filterOptions?.portfolios.map((value) => ({ label: value, value })) ?? [],
        values: filters.portfolios,
      },
      {
        id: 'region',
        label: 'Region',
        isLoading,
        error,
        onRetry: retryOptions,
        onChange: (regions) => setFilters((current) => ({ ...current, regions })),
        options: filterOptions?.regions.map((value) => ({ label: value, value })) ?? [],
        values: filters.regions,
      },
      {
        id: 'facility',
        label: 'Facility',
        isLoading,
        error,
        onRetry: retryOptions,
        onChange: (facilities) => setFilters((current) => ({ ...current, facilities })),
        options: filterOptions?.facilities.map((value) => ({ label: value, value })) ?? [],
        values: filters.facilities,
      },
    ],
    [filterOptions, filters, setFilters, isLoading, error, retryOptions],
  )

  return <TabFilterBar ariaLabel="Overall filters" filters={filterBarFilters} />
}
