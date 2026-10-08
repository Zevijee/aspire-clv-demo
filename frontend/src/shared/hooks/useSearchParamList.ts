import { useReportSearchParams } from '../components/ReportSearchContext'

/** A multi-select report filter kept in the URL as one repeated parameter, so
 * the header dropdown and a chart that sets the same filter share it, and a
 * refresh or a shared link keeps it. */
export function useSearchParamList(param: string) {
  const [params, setParams] = useReportSearchParams()
  const values = params.getAll(param)
  const set = (next: string[]) => {
    const updated = new URLSearchParams(params)
    updated.delete(param)
    next.forEach(value => updated.append(param, value))
    setParams(updated)
  }
  return {
    values,
    set,
    // A chart slice adds or removes its own value.
    toggle: (value: string) => set(values.includes(value) ? values.filter(item => item !== value) : [...values, value]),
    clear: () => set([]),
  }
}
