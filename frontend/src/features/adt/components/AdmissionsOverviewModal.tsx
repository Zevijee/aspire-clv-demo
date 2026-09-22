import { useState } from 'react'
import { Modal } from 'antd'
import { AdmissionsTesting } from './AdmissionsTesting'
import { AdmissionsLogs } from './AdmissionsLogs'
import { DischargesOverview, type DischargeSelection } from './DischargesOverview'
import { DischargesLogs } from './DischargesLogs'
import { NetChangeOverview } from './NetChangeOverview'
import { formatPayerType } from '../api/admissions'
import type { OverviewSelection } from '../utils/admissionsOverviewFilters'
import { ReportSearchProvider, useReportSearchParams } from '../../../shared/components/ReportSearchContext'

export type AdmissionsMonthSelection = { start: string; end: string; path: string[]; payers: string[]; report?: 'admissions' | 'discharges' | 'net-change' }

function Content({ month }: { month: AdmissionsMonthSelection }) {
  const [params, setParams] = useReportSearchParams()
  const [selection, setSelection] = useState<OverviewSelection>({ payers: month.payers, sources: [],
    scope: month.path.length ? { state: month.path[0], portfolio: month.path[1], region: month.path[2], facility: month.path[3] } : null })
  const [dischargeSelection, setDischargeSelection] = useState<DischargeSelection>({
    scope: month.path.length ? { state: month.path[0], portfolio: month.path[1],
      region: month.path[2], facility: month.path[3] } : null,
    payers: month.payers.map(formatPayerType), destinations: [],
  })
  if (month.report === 'net-change') return <NetChangeOverview />
  return params.get('view') === 'logs' ? <>
    <button type="button" className="drilldown-table__link" onClick={() => {
      const next = new URLSearchParams(params); next.set('view', 'testing'); setParams(next)
    }}>Back to Overview</button>
    <div className="report-detail-modal__table">{month.report === 'discharges' ? <DischargesLogs /> : <AdmissionsLogs />}</div>
  </> : month.report === 'discharges'
    ? <DischargesOverview selection={dischargeSelection} onChange={setDischargeSelection} />
    : <AdmissionsTesting selection={selection} onChangeSelection={setSelection} />
}

export function AdmissionsOverviewModal({ month, onClose }: { month: AdmissionsMonthSelection | null; onClose: () => void }) {
  const title = month?.report === 'net-change' ? 'Net Change' : month?.report === 'discharges' ? 'Discharges' : 'Admissions'
  const initialParams = new URLSearchParams(month ? { start_date: month.start, end_date: month.end } : {})
  if (month?.report === 'net-change') {
    month.path.forEach(part => initialParams.append('net_scope', part))
    month.payers.forEach(payer => initialParams.append('net_payer', payer))
  }
  return <Modal open={month !== null} onCancel={onClose} footer={null} destroyOnHidden
    title={month ? `${title} Overview: ${month.start} to ${month.end}` : `${title} Overview`}
    width="calc(100vw - 48px)" className="net-change-daily-modal"
    style={{ top: 24, paddingBottom: 0, maxWidth: 'calc(100vw - 48px)' }}>
    {month && <ReportSearchProvider key={JSON.stringify(month)} initialParams={initialParams}>
      <div className="admissions-overview-modal__content"><Content month={month} /></div>
    </ReportSearchProvider>}
  </Modal>
}
