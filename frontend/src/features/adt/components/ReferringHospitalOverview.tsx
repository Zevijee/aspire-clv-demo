import { useState } from 'react'
import { Checkbox } from 'antd'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import dayjs from 'dayjs'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { useSearchParams } from 'react-router-dom'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { Kpis } from '../../../shared/components/Kpis'
import { DataState } from '../../../shared/components/DataState'
import { AdmissionsPayerFilter } from './AdmissionsPayerFilter'
import {
  BASELINE_MONTHS, COMPARED_MONTHS, RECENT_MONTHS, compareMonths,
  type HospitalPerformance, type ReceivingFacility,
} from '../api/referringHospitalPerformance'
import { useReferringHospitalPerformance } from '../hooks/useReferringHospitalPerformance'

type Comparison = Pick<HospitalPerformance, 'usual_average' | 'recent_average' | 'difference_percent'>
const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 })
const performanceRank: Record<string, number> = {
  'Strong growth': 7, Growing: 6, 'Slight growth': 5, Stable: 4,
  'Slight decline': 3, Declining: 2, 'Sharp decline': 1,
  'New/returning': 0, 'No recent activity': -1,
}
const monthLabel = (month: string) => new Intl.DateTimeFormat('en-US',
  { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${month}-01T00:00:00Z`))

export function ReferringHospitalOverview() {
  const [params] = useSearchParams()
  const payers = params.getAll('referring_payer')
  const [selected, setSelected] = useState<HospitalPerformance | null>(null)
  const [selectedFacilities, setSelectedFacilities] = useState<string[]>([])
  const [modalPayers, setModalPayers] = useState<string[]>([])

  const report = useReferringHospitalPerformance(payers)
  const months = report.data?.months ?? []
  // One hospital at a time, so its receiving facilities carry their own month
  // series. The list response leaves those empty: 384 hospitals never need them.
  const detail = useReferringHospitalPerformance(modalPayers, selected?.hospital ?? null, !selected)
  const detailMonths = detail.data?.months ?? []
  const detailHospital = detail.data && selected
    ? detail.data.items.find(row => row.hospital === selected.hospital)
      // A hospital that referred nobody under the modal's payer filter is absent
      // from the response rather than an error. Show it at zero, so changing the
      // filter reads as no referrals instead of as an empty modal.
      ?? { ...selected, months: detail.data.months.map(() => 0), receiving_facilities: [] }
    : undefined
  const facilities = detailHospital?.receiving_facilities ?? []
  // Selecting facilities re-totals the hospital from the series already loaded,
  // rather than asking the server for a narrower cut of the same rows.
  const modalHospital = selected && detailHospital ? (() => {
    const included = facilities.filter(row =>
      selectedFacilities.length === 0 || selectedFacilities.includes(row.facility_id))
    const values = detailMonths.map((_, index) =>
      included.reduce((total, row) => total + (row.months[index] ?? 0), 0))
    return { ...detailHospital, months: values, ...compareMonths(values) }
  })() : null

  const periodLabel = (first: number, last: number) => months.length
    ? `${monthLabel(months[first])} - ${monthLabel(months[last])}` : ''
  const recentPeriod = periodLabel(months.length - RECENT_MONTHS, months.length - 1)
  const usualPeriod = periodLabel(months.length - COMPARED_MONTHS, months.length - RECENT_MONTHS - 1)
  const status = (row: Comparison) => {
    if (row.usual_average === 0) return row.recent_average > 0 ? 'New/returning' : 'No recent activity'
    const percentage = row.difference_percent ?? 0
    return percentage >= 20 ? 'Strong growth' : percentage >= 10 ? 'Growing' : percentage >= 5 ? 'Slight growth'
      : percentage > -5 ? 'Stable' : percentage > -10 ? 'Slight decline' : percentage > -20 ? 'Declining' : 'Sharp decline'
  }
  const differenceText = (row: HospitalPerformance) => {
    if (row.difference === 0) return 'No change'
    const amount = number(Math.abs(row.difference))
    const percentage = row.difference_percent === null ? '' : ` (${row.difference > 0 ? '+' : ''}${number(row.difference_percent)}%)`
    return `${amount} ${row.difference > 0 ? 'more' : 'fewer'}/month${percentage}`
  }
  const columns: TableColumn<HospitalPerformance>[] = [
    { id: 'hospital', header: 'Hospital', isRowHeader: true, value: row => row.hospital,
      // The name opens the detail, as a resident's name does on Residents; the
      // rest of the row is plain, so selecting text in it does not open anything.
      format: (_, row) => <button type="button" className="drilldown-table__link" onClick={() => {
        setSelectedFacilities([])
        setModalPayers(payers)
        setSelected(row)
      }}>{row.hospital}</button> },
    { id: 'state', header: 'State', filterable: true, value: row => row.state ?? 'Unassigned' },
    { id: 'portfolio', header: 'Portfolio', filterable: true, value: row => row.portfolio ?? 'Unassigned' },
    { id: 'region', header: 'Region', filterable: true, value: row => row.region ?? 'Unassigned' },
    { id: 'facilities', header: 'Facilities', numeric: true, value: row => row.receiving_facilities?.length ?? 0 },
    { id: 'performance', header: 'Performance', filterable: true, value: status,
      sortValue: row => performanceRank[status(row)], initialSortDirection: 'descending',
      format: (_, row) => <span className={['Stable', 'No recent activity', 'New/returning'].includes(status(row)) ? undefined
        : row.difference > 0 ? 'report-table__change--favorable' : 'report-table__change--adverse'}
        title={`Last ${RECENT_MONTHS} complete months versus the preceding ${BASELINE_MONTHS}: thresholds at +/-5%, +/-10%, and +/-20%.`}>{status(row)}</span> },
    { id: 'recent', header: 'Recent avg/month', numeric: true, value: row => row.recent_average,
      format: value => <span title={`Last ${RECENT_MONTHS} complete months: ${recentPeriod}`}>{number(Number(value))}</span> },
    { id: 'usual', header: 'Usual avg/month', numeric: true, value: row => row.usual_average,
      format: value => <span title={`Preceding ${BASELINE_MONTHS} months: ${usualPeriod}`}>{number(Number(value))}</span> },
    { id: 'difference', header: 'Difference', numeric: true, value: row => row.difference,
      change: { favorable: 'increase' }, format: (_, row) => differenceText(row), exportValue: differenceText },
  ]
  return <><div className="referring-hospitals-table">
    <Table title="All hospitals"
      subtitle={`Last ${RECENT_MONTHS} complete months compared with the preceding ${BASELINE_MONTHS} months. Monthly averages include zero-referral months.`}
      columns={columns} rows={report.data?.items ?? []} getRowKey={row => row.hospital}
      searchable internalScroll stickyFirstColumn
      initialSort={{ columnId: 'hospital', direction: 'ascending' }}
      loading={report.loading} error={report.error} onRetry={report.onRetry}
      emptyMessage="No hospitals match the selected filters."
      csvFileName="hospital-referral-performance.csv" />
  </div>
    <FullScreenModal open={selected !== null} onClose={() => setSelected(null)} destroyOnHidden
      title={selected ? <div className="hospital-detail-header">
        <div>
        <div>{selected.hospital} — Monthly admissions</div>
        <div className="hospital-detail-location">
          State: {selected.state} · Portfolio: {selected.portfolio} · Region: {selected.region}
        </div>
        </div>
        <AdmissionsPayerFilter values={modalPayers} onChange={setModalPayers} />
      </div> : 'Monthly admissions'}>
      {detail.loading || detail.error ? <DataState loading={detail.loading} error={detail.error}
        label="hospital details" onRetry={detail.onRetry} /> : selected && modalHospital && <div className="hospital-detail">
        <Kpis items={[
          { header: 'Performance', value: status(modalHospital), trend: {
            direction: Math.abs(modalHospital.difference_percent ?? 0) < 5 ? 'flat' : modalHospital.difference > 0 ? 'up' : 'down',
            tone: Math.abs(modalHospital.difference_percent ?? 0) < 5 ? 'neutral' : modalHospital.difference > 0 ? 'positive' : 'negative',
            value: '', label: 'Recent vs historical average',
          } },
          { header: 'Recent avg/month', value: number(modalHospital.recent_average), trend: {
            tone: 'neutral', value: '', label: `Last ${RECENT_MONTHS} complete months`,
          } },
          { header: 'Historical avg/month', value: number(modalHospital.usual_average), trend: {
            tone: 'neutral', value: '', label: `Preceding ${BASELINE_MONTHS} complete months`,
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
          <span style={{ color: 'var(--color-chart-series-primary)' }}>■ Recent {RECENT_MONTHS} months</span>
          <span style={{ color: 'var(--color-table-change-favorable)' }}>■ Baseline {BASELINE_MONTHS} months</span>
        </div>}
        subtitle={`These ${COMPARED_MONTHS} complete months are the preceding ${BASELINE_MONTHS}-month baseline followed by the recent ${RECENT_MONTHS} months.`}
        items={detailMonths.map((month, index) => ({ date: `${month}-01`,
          color: index >= detailMonths.length - RECENT_MONTHS ? 'var(--color-chart-series-primary)' : 'var(--color-table-change-favorable)',
          end_date: dayjs(`${month}-01`).endOf('month').format('YYYY-MM-DD'), value: modalHospital.months[index] ?? 0 })).slice(-COMPARED_MONTHS)}
        variant="bar" interval="month" height={400} valueLabel="Admissions" showDailyAverage />
        <div className="hospital-detail-split__facilities">
          <Table title={`${facilities.length} receiving ${facilities.length === 1 ? 'facility' : 'facilities'}`} showRowCount={false} subtitle={selectedFacilities.length === 0
            ? 'All facilities shown. Select facilities to narrow this view.'
            : `${selectedFacilities.length} of ${facilities.length} selected. Select facilities to update this view.`}
            columns={[
              { id: 'facility', header: 'Facility', isRowHeader: true, value: row => row.facility,
                format: (_, row) => <><Checkbox checked={selectedFacilities.includes(row.facility_id)}
                  aria-label={`Include ${row.facility}`}
                  onClick={event => event.stopPropagation()}
                  onChange={event => setSelectedFacilities(current => event.target.checked
                    ? [...current, row.facility_id] : current.filter(id => id !== row.facility_id))} />
                  <span style={{ marginLeft: 'var(--space-2)' }}>{row.facility}</span>
                </> },
              { id: 'admissions', header: 'Admissions', numeric: true, value: row => row.admissions },
              { id: 'performance', header: 'Performance', value: row => status(compareMonths(row.months)),
                sortValue: row => performanceRank[status(compareMonths(row.months))], initialSortDirection: 'descending',
                format: (_, row) => {
                  const performance = compareMonths(row.months)
                  const label = status(performance)
                  return <span title={`Last ${RECENT_MONTHS} complete months vs preceding ${BASELINE_MONTHS}-month average`}
                    className={['Stable', 'New/returning', 'No recent activity'].includes(label) ? undefined : (performance.difference_percent ?? 0) > 0
                      ? 'report-table__change--favorable' : 'report-table__change--adverse'}>
                    {label}
                  </span>
                } },
            ] satisfies TableColumn<ReceivingFacility>[]}
            rows={facilities} getRowKey={row => row.facility_id}
            onRowClick={row => setSelectedFacilities(current => current.includes(row.facility_id)
              ? current.filter(id => id !== row.facility_id) : [...current, row.facility_id])}
            headerActions={<div className="hospital-facility-selection-actions">
              <button type="button" className="report-table__filter-action"
                onClick={() => setSelectedFacilities(facilities.map(row => row.facility_id))}>Select all</button>
              <button type="button" className="report-table__filter-action report-table__filter-action--clear"
                onClick={() => setSelectedFacilities([])}>Clear all</button>
            </div>}
            internalScroll initialSort={{ columnId: 'admissions', direction: 'descending' }}
            emptyMessage="No receiving facilities match the selected payers."
            showExport={false} />
        </div>
        </div>
      </div>}
    </FullScreenModal>
  </>
}
