import { useCallback, useLayoutEffect, useRef } from 'react'

/** A chart as the Excel export draws it: the figures it is drawn from, in a
 * small table on the sheet, and an Excel chart of that table beside it. Each
 * value comes with the text the page shows for it, which gives the cell its
 * number format, as a table's cells get theirs. */
export type ExcelChart = {
  kind: 'bar' | 'column' | 'line' | 'doughnut'
  title: string
  /** The heading over the labels: "Source type", "Date". */
  categoryLabel: string
  categories: string[]
  series: {
    name: string
    values: number[]
    /** Each value as the page shows it, for its format: "$1,234", "7.5%". */
    texts: string[]
    /** CSS colours, a token's var() or a literal; per point where given. */
    color?: string
    pointColors?: (string | undefined)[]
    /** Drawn as a dashed line, as a target or average is on the page. */
    reference?: boolean
  }[]
  /** Where a bar's value axis starts, when the page starts it above zero. */
  axisMinimum?: number
}

const charts = new WeakMap<Element, () => ExcelChart | null>()

/** Mark a chart's element as one the Excel export draws: pass the returned ref
 * to the chart's outermost element, and `null` while it has nothing to show
 * (loading, an error, no data). Read only when the report is exported. */
export function useExcelChart(chart: ExcelChart | null) {
  const latest = useRef(chart)
  useLayoutEffect(() => { latest.current = chart })
  return useCallback((element: HTMLElement | null) => {
    if (!element) return
    element.dataset.excelChart = ''
    charts.set(element, () => latest.current)
  }, [])
}

/** The chart an element marked by useExcelChart shows now, if any. */
export function excelChartOf(element: Element) {
  return charts.get(element)?.() ?? null
}
