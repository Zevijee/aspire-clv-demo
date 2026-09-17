import { useEffect, useMemo, useState } from 'react'
import { Modal } from 'antd'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { getReferringHospitals, type ReferringHospital } from '../api/admissions'
import type { DrilldownScope } from '../utils/admissionsDrilldown'
import { getHospitalAdmissionLogsParams } from '../utils/admissionsLogNavigation'

export type HospitalSelection = {
  facilities?: string[]
  scope: DrilldownScope
  label: string
  startDate: string
  endDate: string
  payers: string[]
  sourceTypes: string[]
}

export function ReferringHospitalsModal({ selection, onClose }: {
  selection: HospitalSelection | null
  onClose: () => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const columns: TableColumn<ReferringHospital>[] = [
    { id: 'hospital', header: 'Referring hospital', isRowHeader: true, value: (row) => row.hospital },
    { id: 'admissions', header: 'Admissions', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.admission_count, format: (value, row) => (
        <button type="button" className="admissions-explorer__drill admissions-explorer__drill--count"
          aria-label={`View ${value.toLocaleString()} admissions from ${row.hospital} in Logs`}
          onClick={() => {
            if (!selection) return
            const params = getHospitalAdmissionLogsParams(searchParams, selection.scope,
              selection.startDate, selection.endDate, selection.payers, row.hospital, selection.facilities)
            onClose()
            setSearchParams(params)
          }}>
          {value.toLocaleString()}
        </button>
      ) },
  ]
  const [attempt, setAttempt] = useState(0)
  const key = useMemo(() => ({ selection, attempt }), [selection, attempt])
  const [result, setResult] = useState<{
    key: typeof key; rows?: ReferringHospital[]; error?: string
  } | null>(null)

  useEffect(() => {
    if (!selection) return
    let active = true
    const { scope, startDate, endDate, payers, sourceTypes } = selection
    void getReferringHospitals(startDate, endDate, {
      states: scope ? [scope.state] : [],
      portfolios: scope?.portfolio !== undefined ? [scope.portfolio] : [],
      regions: scope?.region !== undefined ? [scope.region] : [],
      facilities: selection.facilities ?? (scope?.facility !== undefined ? [scope.facility] : []),
      payerTypes: payers,
      sourceTypes,
    }).then(
      (rows) => {
        if (active) setResult({ key, rows: rows.filter((row) => row.admission_count > 0) })
      },
      () => {
        if (active) setResult({ key, error: 'Referring hospitals could not load. Please try again.' })
      },
    )
    return () => { active = false }
  }, [selection, key])

  const response = result?.key === key ? result : null
  return <Modal open={selection !== null} onCancel={onClose} footer={null} centered
    title={`Referring hospitals${selection ? ` · ${selection.label}` : ''}`}
    width="min(720px, calc(100vw - 32px))" destroyOnHidden>
    <div className="report-detail-modal__table">
      <Table key={JSON.stringify(selection)} internalScroll searchable
        title="Hospital admissions" subtitle="Admissions from each hospital in the selected period"
        columns={columns} rows={response?.rows ?? []} getRowKey={(row) => row.hospital}
        loading={selection !== null && response === null} error={response?.error}
        onRetry={() => setAttempt((value) => value + 1)}
        initialSort={{ columnId: 'admissions', direction: 'descending' }}
        csvFileName={`referring-hospitals-${selection?.startDate}-to-${selection?.endDate}.csv`}
        emptyMessage="No referring hospitals match these dates and filters." />
    </div>
  </Modal>
}
