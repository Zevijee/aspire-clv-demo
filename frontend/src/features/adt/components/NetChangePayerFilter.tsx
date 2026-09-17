import { PayerFilter } from './PayerFilter'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'

export function NetChangePayerFilter() {
  const [params, setParams] = useSearchParams()
  return <PayerFilter
    values={params.getAll('net_payer')}
    onChange={(values: string[]) => {
      const next = new URLSearchParams(params)
      next.delete('net_payer')
      values.forEach(value => next.append('net_payer', value))
      setParams(next)
    }}
  />
}
