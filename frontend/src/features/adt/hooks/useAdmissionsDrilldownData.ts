import { useEffect, useMemo, useState } from 'react'

import {
  getAdmissionsByFacilityMetrics,
  getAdmissionsByRegionLevelMetrics,
  getAdmissionsByRegionMetrics,
} from '../api/admissions'

function useMetricsRows<Row>(
  startDate: string,
  endDate: string,
  fetchRows: (startDate: string, endDate: string) => Promise<Row[]>,
) {
  const [attempt, setAttempt] = useState(0)
  // A fresh identity also covers returning to a previously visited date range.
  const key = useMemo(() => ({ startDate, endDate, attempt, fetchRows }), [startDate, endDate, attempt, fetchRows])
  const [response, setResponse] = useState<{ key: typeof key; rows: Row[] } | null>(null)
  const [failure, setFailure] = useState<{ key: typeof key; message: string } | null>(null)

  useEffect(() => {
    let active = true
    void fetchRows(startDate, endDate).then(
      (rows) => {
        if (active) {
          setFailure(null)
          setResponse({ key, rows })
        }
      },
      () => {
        if (active) setFailure({ key, message: 'Admissions could not load. Please try again.' })
      },
    )
    return () => { active = false }
  }, [startDate, endDate, fetchRows, key])

  const result = response?.key === key ? response : null
  const error = failure?.key === key ? failure.message : null
  return {
    rows: result?.rows ?? [],
    loading: result === null && error === null,
    error,
    onRetry: () => setAttempt((current) => current + 1),
  }
}

const emptyPayers: string[] = []

export function useAdmissionsDrilldownData(startDate: string, endDate: string, payers: string[] = emptyPayers, sourceTypes: string[] = emptyPayers) {
  // Start every level together so drilling does not introduce a request waterfall.
  // Each level can resolve or be retried independently of its siblings.
  const loaders = useMemo(() => {
    return {
      portfolios: (start: string, end: string) => getAdmissionsByRegionMetrics(start, end, 'portfolio', payers, sourceTypes),
      regions: (start: string, end: string) => getAdmissionsByRegionLevelMetrics(start, end, payers, sourceTypes),
      facilities: (start: string, end: string) => getAdmissionsByFacilityMetrics(start, end, payers, sourceTypes),
    }
  }, [payers, sourceTypes])
  const portfolios = useMetricsRows(startDate, endDate, loaders.portfolios)
  const regions = useMetricsRows(startDate, endDate, loaders.regions)
  const facilities = useMetricsRows(startDate, endDate, loaders.facilities)
  return { portfolios, regions, facilities }
}
