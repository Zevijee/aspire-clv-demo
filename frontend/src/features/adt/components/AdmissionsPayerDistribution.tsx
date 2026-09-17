import { useEffect, useMemo, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { DonutChart } from '../../../shared/components/charts/DonutChart'
import { formatPayerType, getPayerFacilityCounts, type PayerFacilityCount } from '../api/admissions'
import type { DrilldownScope } from '../utils/admissionsDrilldown'
import { matchesLocation } from '../utils/admissionsOverviewFilters'

export function AdmissionsPayerDistribution({ startDate: suppliedStart, endDate: suppliedEnd, scope = null, selectedPayers = [], sourceTypes = [], onChangePayers, locations = [] }: {
  locations?: string[]
  startDate?: string; endDate?: string; scope?: DrilldownScope
  sourceTypes?: string[]; selectedPayers?: string[]; onChangePayers?: (payers: string[]) => void
} = {}) {
  const [searchParams] = useSearchParams()
  const defaults = getDefaultReportDateRange()
  const startDate = suppliedStart ?? searchParams.get('start_date') ?? defaults.startDate
  const endDate = suppliedEnd ?? searchParams.get('end_date') ?? defaults.endDate
  const [attempt, setAttempt] = useState(0)
  const sourceKey = JSON.stringify(sourceTypes)
  const key = useMemo(() => ({ startDate, endDate, attempt, sourceKey }), [startDate, endDate, attempt, sourceKey])
  const [result, setResult] = useState<{ key: typeof key; rows?: PayerFacilityCount[]; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getPayerFacilityCounts(startDate, endDate, JSON.parse(sourceKey) as string[]).then(
      (rows) => { if (active) setResult({ key, rows }) },
      () => { if (active) setResult({ key, error: 'Payer admissions could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [startDate, endDate, key, sourceKey])
  const response = result?.key === key ? result : null
  const counts = new Map<string, number>()
  for (const row of response?.rows ?? []) {
    if (!matchesLocation(row, locations)) continue
    if (scope !== null && row.state !== scope.state) continue
    if (scope?.portfolio !== undefined && row.portfolio !== scope.portfolio) continue
    if (scope?.region !== undefined && row.region !== scope.region) continue
    if (scope?.facility !== undefined && row.facility !== scope.facility) continue
    counts.set(row.payer_type, (counts.get(row.payer_type) ?? 0) + row.admissions)
  }
  const items = [...counts].sort(([a], [b]) => a.localeCompare(b))
    .map(([payer, value]) => ({ label: formatPayerType(payer), value }))
  return <DonutChart title="Admissions by payer" subtitle={selectedPayers.length ? `Report filtered by ${selectedPayers.map(formatPayerType).join(', ')}` : 'Click payers to filter the report'}
    selectedLabels={selectedPayers.map(formatPayerType)}
    onClear={onChangePayers ? () => onChangePayers([]) : undefined}
    onSelect={onChangePayers ? (label) => {
      const payer = [...new Set([...counts.keys(), ...selectedPayers])].find((value) => formatPayerType(value) === label)
      if (payer) onChangePayers(selectedPayers.includes(payer)
        ? selectedPayers.filter((value) => value !== payer) : [...selectedPayers, payer])
    } : undefined}
    items={items} loading={response === null} error={response?.error}
    onRetry={() => setAttempt((value) => value + 1)} />
}
