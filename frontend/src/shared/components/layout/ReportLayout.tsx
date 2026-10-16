import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { ActiveFiltersProvider } from '../../activeFilters'
import { LocationSheetHost } from '../../locationSheets'

import { ReportTabs, type ReportTabsProps } from './ReportTabs'

// Temporarily hide report side filters while trying the simpler layout.
const showSideFilters = false

type ReportLayoutProps = {
  children?: ReactNode
  tabFilters?: ReactNode
  filters?: ReactNode
  leadingControl?: ReactNode
  tabs?: ReportTabsProps
  titleDetail?: string
  title: string
  internalScroll?: boolean
}

export function ReportLayout({
  children,
  tabFilters,
  filters,
  leadingControl,
  tabs,
  titleDetail,
  title,
  internalScroll = false,
}: ReportLayoutProps) {
  const activeTab = tabs?.tabs.find((tab) => tab.id === tabs.activeTabId)
  const noScroll = internalScroll || activeTab?.noScroll === true
  // This layout stays mounted from one report to the next, and so would its
  // scroll position: each report opens at the top. Only the path counts, so
  // drilling, tabs and filters -- query changes -- keep their place.
  const { pathname } = useLocation()
  const content = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    content.current?.scrollTo({ top: 0, left: 0 })
  }, [pathname])

  // The report's filters announce themselves here; its drilldown bar lists them.
  return (<ActiveFiltersProvider requireHeader>
    <div className="main-panel">
      <header className="app-header">
        <div className="app-header__content">
          {leadingControl}
          <div className="report-title-block">
            <h1>{title}</h1>
            {titleDetail !== undefined && <p className="report-title-detail">{titleDetail}</p>}
          </div>
          {filters}
        </div>
        {tabs !== undefined && <ReportTabs {...tabs} />}
      </header>
      <main
        ref={content}
        className={`content-area ${noScroll ? 'content-area--no-scroll' : ''}`}
        id="main-content"
      >
        <div className={`report-content ${noScroll ? 'report-content--no-scroll' : ''}`}>
          {children}
        </div>
      </main>
      {/* The Excel export's off-screen copies of this report, one per location. */}
      <LocationSheetHost />
      {showSideFilters && tabFilters !== undefined && (
        <div className="content-area__overlay" key={tabs?.activeTabId}>{tabFilters}</div>
      )}
    </div>
  </ActiveFiltersProvider>)
}
