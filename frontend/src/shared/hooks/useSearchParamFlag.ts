import { useReportSearchParams } from '../components/ReportSearchContext'

/** An on/off state kept in the page's search parameters rather than in React
 * state, so it survives the report unmounting. Show all facilities uses it: a
 * count in the modal opens Logs, and returning to the overview -- by its tab or
 * the browser's Back button -- finds the modal still open. Links into Logs copy
 * the current parameters, which is what carries the flag across. */
export function useSearchParamFlag(name: string) {
  const [params, setParams] = useReportSearchParams()
  const on = params.get(name) === '1'
  const set = (value: boolean) => {
    const next = new URLSearchParams(params)
    if (value) next.set(name, '1')
    else next.delete(name)
    setParams(next)
  }
  return [on, set] as const
}
