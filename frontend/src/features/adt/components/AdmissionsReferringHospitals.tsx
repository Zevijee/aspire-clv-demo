import { useEffect, useMemo, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import dayjs from 'dayjs'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getReferringHospitals, type AdmissionsMetricFilters, type ReferringHospital } from '../api/admissions'

const filters: AdmissionsMetricFilters = { facilities: [], payerTypes: [], portfolios: [], regions: [] }
type HospitalRow = Pick<ReferringHospital, 'hospital' | 'admission_count' | 'prior_period_admissions'
  | 'receiving_facility_codes' | 'admissions_change' | 'average_admissions_per_day'
  | 'readmission_count' | 'readmission_within_30_days_count'>
const columns: TableColumn<HospitalRow>[] = [
  { id: 'hospital', header: 'Referring hospital', isRowHeader: true,
    value: (row) => row.hospital },
  { id: 'admissions', header: 'Total admissions', numeric: true, initialSortDirection: 'descending',
    value: (row) => row.admission_count, format: (value) => value.toLocaleString() },
  { id: 'average', header: 'Average per day', numeric: true, initialSortDirection: 'descending',
    value: (row) => row.average_admissions_per_day,
    format: (value) => value.toLocaleString(undefined, { maximumFractionDigits: 1 }) },
  { id: 'prior', header: 'Prior-period admissions', numeric: true, initialSortDirection: 'descending',
    value: (row) => row.prior_period_admissions, format: (value) => value.toLocaleString() },
  { id: 'change', header: 'Admissions vs prior period', numeric: true, initialSortDirection: 'descending',
    value: (row) => row.admissions_change, change: { favorable: 'increase' } },
  { id: 'readmissions', header: 'Readmissions', numeric: true, initialSortDirection: 'descending',
    value: (row) => row.readmission_count, format: (value) => value.toLocaleString() },
  { id: 'readmissions-30-days', header: 'Readmissions within 30 days', numeric: true,
    initialSortDirection: 'descending', value: (row) => row.readmission_within_30_days_count,
    format: (value) => value.toLocaleString() },
  { id: 'receiving-facilities', header: 'Receiving facilities', numeric: true,
    initialSortDirection: 'descending', value: (row) => row.receiving_facility_codes.length,
    format: (value) => value.toLocaleString() },
]

function getHospitalTotal(rows: HospitalRow[], days: number): HospitalRow | null {
  if (rows.length <= 1) return null
  const total: HospitalRow = {
    hospital: 'Total', admission_count: 0, prior_period_admissions: 0,
    receiving_facility_codes: [...new Set(rows.flatMap((row) => row.receiving_facility_codes))],
    admissions_change: 0, average_admissions_per_day: 0,
    readmission_count: 0, readmission_within_30_days_count: 0,
  }
  for (const row of rows) {
    total.admission_count += row.admission_count
    total.prior_period_admissions += row.prior_period_admissions
    total.readmission_count += row.readmission_count
    total.readmission_within_30_days_count += row.readmission_within_30_days_count
  }
  total.admissions_change = total.admission_count - total.prior_period_admissions
  total.average_admissions_per_day = total.admission_count / days
  return total
}

export function AdmissionsReferringHospitals() {
  const [searchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const [attempt, setAttempt] = useState(0)
  const key = useMemo(() => ({ startDate, endDate, attempt }), [startDate, endDate, attempt])
  const [result, setResult] = useState<{ key: typeof key; rows?: ReferringHospital[]; error?: string } | null>(null)
  useEffect(() => {
    let active = true
    void getReferringHospitals(startDate, endDate, filters).then(
      (rows) => { if (active) setResult({ key, rows }) },
      () => { if (active) setResult({ key, error: 'Referring hospitals could not load. Please try again.' }) },
    )
    return () => { active = false }
  }, [startDate, endDate, key])
  const response = result?.key === key ? result : null
  return <Table internalScroll searchable stickyFooterRow title="Referring hospitals"
    subtitle="Hospital admissions compared with the immediately preceding period of the same length"
    rows={response?.rows ?? []} columns={columns}
    getFooterRow={(visibleRows) => getHospitalTotal(visibleRows, days)}
    loading={response === null} error={response?.error}
    onRetry={() => setAttempt((value) => value + 1)}
    csvFileName={`referring-hospitals-${startDate}-to-${endDate}.csv`}
    initialSort={{ columnId: 'admissions', direction: 'descending' }} getRowKey={(row) => row.hospital}
    emptyMessage="No hospital admissions in the selected or prior period." />
}
