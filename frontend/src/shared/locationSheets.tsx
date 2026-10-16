import { createContext, useContext, useEffect, useRef, useState, type Context, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useReportSearchParams, ReportSearchProvider } from './components/ReportSearchContext'
import { ActiveFiltersProvider } from './activeFilters'
import { capturePage, type PageCapture } from './reportExcel'

/** The Excel export's sheet for each location one level below the drilldown's
 * current one -- each state at the top, each portfolio in a state, each region
 * in a portfolio, each facility in a region -- as the report shows it drilled
 * into, built quietly: the report gives, for each location in its drilldown
 * table, itself drawn there (useLocationSheets); the export draws each off the
 * screen, where its own requests load its own figures, reads its tables and
 * charts as it reads the page, and removes it. The page on screen never moves.
 *
 * An off-screen copy has its own search parameters and active filters, so
 * nothing it does reaches the page, and registers no locations of its own. */

/** A location of the drilldown and the report drawn at it. */
export type LocationSheet = { name: string; render: () => ReactNode }

type Job = { id: number; node: ReactNode; container: HTMLElement }
type Registry = {
  /** Inside an off-screen copy: its own drilldown is not the export's. */
  offScreen: Context<boolean>
  providers: Set<() => LocationSheet[]>
  addJob: ((job: Job) => void) | null
  removeJob: ((id: number) => void) | null
  nextId: number
}

// Kept on the window, not in this module: the dev server swaps an edited module
// into an open page, and a second copy of this state had the reports
// registering their locations where the export no longer looked.
const registry: Registry = (globalThis as { __clearviewLocationSheets?: Registry }).__clearviewLocationSheets ??= {
  offScreen: createContext(false), providers: new Set(), addJob: null, removeJob: null, nextId: 1 }
const OffScreen = registry.offScreen
const { providers } = registry

/** Give the Excel export a sheet for each location in the drilldown table:
 * its name and the report drawn there -- the same component, its drilldown
 * starting at that location. Asked at export time, for the rows on screen then. */
export function useLocationSheets(build: () => LocationSheet[]) {
  const offScreen = useContext(OffScreen)
  const latest = useRef(build)
  useEffect(() => { latest.current = build })
  useEffect(() => {
    if (offScreen) return
    const provider = () => latest.current()
    providers.add(provider)
    return () => { providers.delete(provider) }
  }, [offScreen])
}

/** Whether this is an off-screen copy drawn for the export. */
export const useOffScreen = () => useContext(OffScreen)


/** Draws the export's off-screen copies inside the app, so they have its
 * router, sign-in and grouping. ReportLayout holds one. */
export function LocationSheetHost() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [params] = useReportSearchParams()
  useEffect(() => {
    registry.addJob = job => setJobs(current => [...current, job])
    registry.removeJob = id => setJobs(current => current.filter(job => job.id !== id))
    return () => { registry.addJob = null; registry.removeJob = null }
  }, [])
  // The page's parameters less Show all facilities: its modal opens over the
  // whole screen, wherever the copy is.
  const copied = () => {
    const next = new URLSearchParams(params)
    next.delete('all_facilities')
    return next
  }
  return <>{jobs.map(job => createPortal(
    <OffScreen.Provider value={true}>
      <ReportSearchProvider initialParams={copied()}>
        <ActiveFiltersProvider><div className="report-content">{job.node}</div></ActiveFiltersProvider>
      </ReportSearchProvider>
    </OffScreen.Provider>, job.container, job.id))}</>
}

// Loaded when no spinner has shown for this many polls in a row: a view's
// tables, prior period and charts load side by side.
const SETTLED_POLLS = 4
const POLL_MS = 150
const LOAD_TIMEOUT_MS = 60_000
// Copies drawn at once: each makes the report's requests.
const AT_ONCE = 3

const wait = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

/** Draw one location off the screen at the page's width, wait for it to load,
 * and read it. */
async function capture(sheet: LocationSheet, content: HTMLElement): Promise<PageCapture> {
  const { addJob } = registry
  if (!addJob) throw new Error('The report cannot draw its locations for the export.')
  const container = document.createElement('div')
  // The page's own content classes, so the copy lays out as the page does.
  container.className = `${content.className} report-location-sheet`
  container.style.width = `${content.getBoundingClientRect().width}px`
  container.setAttribute('aria-hidden', 'true')
  container.inert = true
  document.body.append(container)
  const id = registry.nextId++
  addJob({ id, node: sheet.render(), container })
  try {
    const start = Date.now()
    let steady = 0
    while (steady < SETTLED_POLLS) {
      if (Date.now() - start > LOAD_TIMEOUT_MS) throw new Error(`${sheet.name} did not finish loading.`)
      await wait(POLL_MS)
      const drawn = container.querySelector('.report-table, [data-excel-chart]') !== null
      steady = drawn && !container.querySelector('.data-state__spinner') ? steady + 1 : 0
    }
    return capturePage(container)
  } finally {
    registry.removeJob?.(id)
    container.remove()
  }
}

/** The drilldown table's location names as the page sorts them: the first
 * table after the breadcrumbs, each row's first cell. */
function shownOrder(content: HTMLElement) {
  const navigation = content.querySelector('.drilldown-navigation')
  const table = navigation && [...content.querySelectorAll('.report-table')]
    .find(card => navigation.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING)
  return [...table?.querySelectorAll(':scope > .report-table__scroll tbody > tr') ?? []]
    .map(row => ((row as HTMLTableRowElement).cells[0]?.textContent ?? '').replace(/\s+/g, ' ').trim())
}

/** Every location the report gives, read off the screen, a few at a time, in
 * the order the drilldown table shows them. */
export async function locationPages(content: HTMLElement) {
  const order = shownOrder(content)
  const place = (name: string) => order.includes(name) ? order.indexOf(name) : order.length
  const sheets = [...providers].flatMap(provider => provider())
    .map((sheet, index) => ({ sheet, index }))
    .sort((a, b) => place(a.sheet.name) - place(b.sheet.name) || a.index - b.index)
    .map(({ sheet }) => sheet)
  const captures: PageCapture[] = new Array(sheets.length)
  let next = 0
  await Promise.all(Array.from({ length: Math.min(AT_ONCE, sheets.length) }, async () => {
    while (next < sheets.length) {
      const index = next++
      captures[index] = await capture(sheets[index], content)
    }
  }))
  return sheets.map((sheet, index) => ({ name: sheet.name, capture: captures[index] }))
}
