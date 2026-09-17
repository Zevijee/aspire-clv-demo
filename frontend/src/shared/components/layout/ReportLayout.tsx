import type { ReactNode } from 'react'

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

  return (
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
        className={`content-area ${noScroll ? 'content-area--no-scroll' : ''}`}
        id="main-content"
      >
        <div className={`report-content ${noScroll ? 'report-content--no-scroll' : ''}`}>
          {children}
        </div>
      </main>
      {showSideFilters && tabFilters !== undefined && (
        <div className="content-area__overlay" key={tabs?.activeTabId}>{tabFilters}</div>
      )}
    </div>
  )
}
