import { useEffect, useState } from 'react'
import { Checkbox, Modal } from 'antd'
import dayjs from 'dayjs'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { useSearchParams } from 'react-router-dom'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { Kpis } from '../../../shared/components/Kpis'
import { DataState } from '../../../shared/components/DataState'
import { PayerFilter } from './PayerFilter'

type Hospital = {
  receiving_facilities: { facility_code: string; facility: string; admissions: number; months: number[] }[]
  state: string; portfolio: string; region: string
  usual_average: number; difference: number; difference_percent: number | null
  current_month_average_per_day: number; previous_month_admissions: number
  six_month_average: number; year_average: number
  hospital: string; months: number[]; recent_average: number; previous_average: number
  change_percent: number | null; historical_average: number; change_vs_average: number
}
type Performance = { items: Hospital[]; months: string[]; start_date: string; end_date: string }
const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 })
const performanceRank: Record<string, number> = {
  'Strong growth': 7, Growing: 6, 'Slight growth': 5, Stable: 4,
  'Slight decline': 3, Declining: 2, 'Sharp decline': 1,
  'New/returning': 0, 'No recent activity': -1,
}
const facilityPerformance = (row: Hospital['receiving_facilities'][number]) => {
  const recent = row.months.slice(-3).reduce((sum, value) => sum + value, 0) / 3
  const baseline = row.months.slice(-27, -3).reduce((sum, value) => sum + value, 0) / 24
  return { recent_average: recent, usual_average: baseline,
    difference_percent: baseline ? (recent - baseline) / baseline * 100 : null }
}
const monthLabel = (month: string) => new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${month}-01T00:00:00Z`))

export function ReferringHospitalOverview() {
  const [selected, setSelected] = useState<{ hospital: Hospital; months: string[] } | null>(null)
  const [selectedFacilities, setSelectedFacilities] = useState<string[]>([])
  const [modalPayers, setModalPayers] = useState<string[]>([])
  const [modalRequestState, setModalRequestState] = useState<{ key: string; error?: string } | null>(null)
  const [modalRetry, setModalRetry] = useState(0)
  const modalHospital = selected ? (() => {
    const values = selected.months.map((_, index) => selected.hospital.receiving_facilities
      .filter(row => selectedFacilities.length === 0 || selectedFacilities.includes(row.facility_code))
      .reduce((total, row) => total + (row.months[index] ?? 0), 0))
    const recent = values.slice(-3).reduce((sum, value) => sum + value, 0) / 3
    const usual = values.slice(-27, -3).reduce((sum, value) => sum + value, 0) / 24
    return { ...selected.hospital, months: values, recent_average: recent, usual_average: usual,
      difference: recent - usual, difference_percent: usual ? (recent - usual) / usual * 100 : null }
  })() : null
  const [params] = useSearchParams()
  const request = new URLSearchParams()
  params.getAll('referring_payer').forEach(value => request.append('payer_type', value))
  const query = request.toString()
  const modalRequest = new URLSearchParams()
  modalPayers.forEach(value => modalRequest.append('payer_type', value))
  const hospitalName = selected?.hospital.hospital
  if (hospitalName) modalRequest.set('hospital', hospitalName)
  const modalQuery = modalRequest.toString()
  const modalKey = JSON.stringify([hospitalName, modalQuery, modalRetry])
  useEffect(() => {
    if (!hospitalName) return
    const controller = new AbortController()
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/adt/admissions/referring-hospital-performance?${modalQuery}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 503
          ? 'Hospital reporting needs to be seeded before this view is available.'
          : 'Hospital details could not load. Please try again.')
        return await response.json() as Performance
      }).then(data => {
        if (controller.signal.aborted) return
        const hospital = data.items.find(row => row.hospital === hospitalName)
        setSelected(current => current && current.hospital.hospital === hospitalName ? {
          months: data.months,
          hospital: hospital ?? { ...current.hospital, receiving_facilities: [], months: data.months.map(() => 0) },
        } : current)
        setModalRequestState({ key: modalKey })
      }).catch((error: Error) => {
        if (!controller.signal.aborted) setModalRequestState({ key: modalKey, error: error.message })
      })
    return () => controller.abort()
  }, [hospitalName, modalQuery, modalKey])
  const modalLoading = modalRequestState?.key !== modalKey
  const modalError = modalRequestState?.key === modalKey ? modalRequestState.error : undefined
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([query, retry])
  const [response, setResponse] = useState<{ key: string; data?: Performance; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/adt/admissions/referring-hospital-performance?${query}`, { signal: controller.signal })
      .then(async result => {
        if (!result.ok) throw new Error(result.status === 503
          ? 'Hospital reporting needs to be seeded before this report is available.'
          : 'Hospital performance could not load. Please try again.')
        return await result.json() as Performance
      }).then(data => { if (!controller.signal.aborted) setResponse({ key, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setResponse({ key, error: error.message }) })
    return () => controller.abort()
  }, [query, key])
  const result = response?.key === key ? response : null
  const months = result?.data?.months ?? []
  const periodLabel = (first: number, last: number) => months.length ? `${monthLabel(months[first])} - ${monthLabel(months[last])}` : ''
  const status = (row: Pick<Hospital, 'usual_average' | 'recent_average' | 'difference_percent'>) => {
    if (row.usual_average === 0) return row.recent_average > 0 ? 'New/returning' : 'No recent activity'
    const percentage = row.difference_percent ?? 0
    return percentage >= 20 ? 'Strong growth' : percentage >= 10 ? 'Growing' : percentage >= 5 ? 'Slight growth'
      : percentage > -5 ? 'Stable' : percentage > -10 ? 'Slight decline' : percentage > -20 ? 'Declining' : 'Sharp decline'

  }
  const differenceText = (row: Hospital) => {
    if (row.difference === 0) return 'No change'
    const amount = number(Math.abs(row.difference))
    const percentage = row.difference_percent === null ? '' : ` (${row.difference > 0 ? '+' : ''}${number(row.difference_percent)}%)`
    return `${amount} ${row.difference > 0 ? 'more' : 'fewer'}/month${percentage}`
  }
  const columns: TableColumn<Hospital>[] = [
    { id: 'hospital', header: 'Hospital', isRowHeader: true, value: row => row.hospital },
    { id: 'state', header: 'State', filterable: true, value: row => row.state ?? 'Unassigned' },
    { id: 'portfolio', header: 'Portfolio', filterable: true, value: row => row.portfolio ?? 'Unassigned' },
    { id: 'region', header: 'Region', filterable: true, value: row => row.region ?? 'Unassigned' },
    { id: 'facilities', header: 'Facilities', numeric: true, value: row => row.receiving_facilities?.length ?? 0 },
    { id: 'performance', header: 'Performance', filterable: true, value: status,
      sortValue: row => performanceRank[status(row)], initialSortDirection: 'descending',
      format: (_, row) => <span className={['Stable', 'No recent activity', 'New/returning'].includes(status(row)) ? undefined
        : row.difference > 0 ? 'report-table__change--favorable' : 'report-table__change--adverse'}
        title="Last 3 complete months versus the preceding 24: thresholds at +/-5%, +/-10%, and +/-20%.">{status(row)}</span> },
    { id: 'recent', header: 'Recent avg/month', numeric: true, value: row => row.recent_average,
      format: value => <span title={`Last 3 complete months: ${periodLabel(33, 35)}`}>{number(Number(value))}</span> },
    { id: 'usual', header: 'Usual avg/month', numeric: true, value: row => row.usual_average,
      format: value => <span title={`Preceding 24 months: ${periodLabel(9, 32)}`}>{number(Number(value))}</span> },
    { id: 'difference', header: 'Difference', numeric: true, value: row => row.difference,
      change: { favorable: 'increase' }, format: (_, row) => differenceText(row), exportValue: differenceText },
  ]
  return <><div className="referring-hospitals-table">
    <Table title="All hospitals"
      subtitle="Last 3 complete months compared with the preceding 24 months. Monthly averages include zero-referral months."
      columns={columns} rows={result?.data?.items ?? []} getRowKey={row => row.hospital}
      searchable internalScroll stickyFirstColumn
      onRowClick={hospital => {
        setSelectedFacilities([])
        setModalPayers(params.getAll('referring_payer'))
        setModalRequestState(null)
        setSelected({ hospital, months: [...months] })
      }}
      initialSort={{ columnId: 'hospital', direction: 'ascending' }}
      loading={!result} error={result?.error} onRetry={() => setRetry(value => value + 1)}
      emptyMessage="No hospitals match the selected filters."
      csvFileName="hospital-referral-performance.csv" />
  </div>
    <Modal open={selected !== null} onCancel={() => setSelected(null)} footer={null} destroyOnHidden
      title={selected ? <div className="hospital-detail-header">
        <div>
        <div>{selected.hospital.hospital} — Monthly admissions</div>
        <div className="hospital-detail-location">
          State: {selected.hospital.state} · Portfolio: {selected.hospital.portfolio} · Region: {selected.hospital.region}
        </div>
        </div>
        <PayerFilter values={modalPayers} onChange={setModalPayers} />
      </div> : 'Monthly admissions'}
      width="calc(100vw - 48px)" className="net-change-daily-modal"
      style={{ top: 24, paddingBottom: 0, maxWidth: 'calc(100vw - 48px)' }}>
      {modalLoading || modalError ? <DataState loading={modalLoading} error={modalError}
        label="hospital details" onRetry={() => setModalRetry(value => value + 1)} /> : selected && modalHospital && <div className="hospital-detail">
        <Kpis items={[
          { header: 'Performance', value: status(modalHospital), trend: {
            direction: Math.abs(modalHospital.difference_percent ?? 0) < 5 ? 'flat' : modalHospital.difference > 0 ? 'up' : 'down',
            tone: Math.abs(modalHospital.difference_percent ?? 0) < 5 ? 'neutral' : modalHospital.difference > 0 ? 'positive' : 'negative',
            value: '', label: 'Recent vs historical average',
          } },
          { header: 'Recent avg/month', value: number(modalHospital.recent_average), trend: {
            tone: 'neutral', value: '', label: 'Last 3 complete months',
          } },
          { header: 'Historical avg/month', value: number(modalHospital.usual_average), trend: {
            tone: 'neutral', value: '', label: 'Preceding 24 complete months',
          } },
          { header: 'Variance', value: `${modalHospital.difference > 0 ? '+' : ''}${number(modalHospital.difference)}/month`, trend: {
            direction: modalHospital.difference === 0 ? 'flat' : modalHospital.difference > 0 ? 'up' : 'down',
            tone: modalHospital.difference === 0 ? 'neutral' : modalHospital.difference > 0 ? 'positive' : 'negative',
            value: modalHospital.difference_percent === null ? '' : `${modalHospital.difference_percent > 0 ? '+' : ''}${number(modalHospital.difference_percent)}%`,
            label: modalHospital.difference_percent === null ? 'No historical baseline' : 'vs historical average',
          } },
        ]} />
        <div className="hospital-detail-split"><LineChart title="Monthly referral trend"
        headerActions={<div className="stacked-ranking-chart__legend">
          <span style={{ color: 'var(--color-chart-series-primary)' }}>■ Recent 3 months</span>
          <span style={{ color: 'var(--color-table-change-favorable)' }}>■ Baseline 24 months</span>
        </div>}
        subtitle="These 27 complete months are the preceding 24-month baseline followed by the recent 3 months."
        items={selected.months.map((month, index) => ({ date: `${month}-01`,
          color: index >= selected.months.length - 3 ? 'var(--color-chart-series-primary)' : 'var(--color-table-change-favorable)',
          end_date: dayjs(`${month}-01`).endOf('month').format('YYYY-MM-DD'), value: modalHospital.months[index] ?? 0 })).slice(-27)}
        variant="bar" interval="month" height={400} valueLabel="Admissions" showDailyAverage />
        <div className="hospital-detail-split__facilities">
          <Table title={`${selected.hospital.receiving_facilities.length} receiving ${selected.hospital.receiving_facilities.length === 1 ? 'facility' : 'facilities'}`} showRowCount={false} subtitle={selectedFacilities.length === 0
            ? 'All facilities shown. Select facilities to narrow this view.'
            : `${selectedFacilities.length} of ${selected.hospital.receiving_facilities.length} selected. Select facilities to update this view.`}
            columns={[
              { id: 'facility', header: 'Facility', isRowHeader: true, value: row => row.facility,
                format: (_, row) => <><Checkbox checked={selectedFacilities.includes(row.facility_code)}
                  aria-label={`Include ${row.facility}`}
                  onClick={event => event.stopPropagation()}
                  onChange={event => setSelectedFacilities(current => event.target.checked
                    ? [...current, row.facility_code] : current.filter(code => code !== row.facility_code))} />
                  <span style={{ marginLeft: 'var(--space-2)' }}>{row.facility}</span>
                </> },
              { id: 'admissions', header: 'Admissions', numeric: true, value: row => row.admissions },
              { id: 'performance', header: 'Performance', value: row => status(facilityPerformance(row)),
                sortValue: row => performanceRank[status(facilityPerformance(row))], initialSortDirection: 'descending',
                format: (_, row) => {
                  const performance = facilityPerformance(row)
                  const label = status(performance)
                  return <span title="Last 3 complete months vs preceding 24-month average"
                    className={['Stable', 'New/returning', 'No recent activity'].includes(label) ? undefined : (performance.difference_percent ?? 0) > 0
                      ? 'report-table__change--favorable' : 'report-table__change--adverse'}>
                    {label}
                  </span>
                } },
            ]}
            rows={selected.hospital.receiving_facilities ?? []} getRowKey={row => row.facility_code}
            onRowClick={row => setSelectedFacilities(current => current.includes(row.facility_code)
              ? current.filter(code => code !== row.facility_code) : [...current, row.facility_code])}
            headerActions={<div className="hospital-facility-selection-actions">
              <button type="button" className="report-table__filter-action"
                onClick={() => setSelectedFacilities(selected.hospital.receiving_facilities.map(row => row.facility_code))}>Select all</button>
              <button type="button" className="report-table__filter-action report-table__filter-action--clear"
                onClick={() => setSelectedFacilities([])}>Clear all</button>
            </div>}
            internalScroll initialSort={{ columnId: 'admissions', direction: 'descending' }}
            emptyMessage="No receiving facilities match the selected payers."
            showExport={false} />
        </div>
        </div>
      </div>}
    </Modal>
  </>
}
