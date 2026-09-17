import { createContext, useContext, useState, type ReactNode } from 'react'
import { useSearchParams, type SetURLSearchParams, createSearchParams } from 'react-router-dom'

const ReportSearchContext = createContext<ReturnType<typeof useSearchParams> | null>(null)

export function ReportSearchProvider({ initialParams, children }: { initialParams: URLSearchParams; children: ReactNode }) {
  const [params, setParams] = useState(initialParams)
  const update: SetURLSearchParams = next => setParams(current => createSearchParams(
    typeof next === 'function' ? next(new URLSearchParams(current)) : next,
  ))
  return <ReportSearchContext.Provider value={[params, update]}>{children}</ReportSearchContext.Provider>
}

export function useReportSearchParams(): ReturnType<typeof useSearchParams> {
  const route = useSearchParams()
  return useContext(ReportSearchContext) ?? route
}
