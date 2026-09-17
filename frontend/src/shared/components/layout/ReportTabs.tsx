export type ReportTab = {
  id: string
  label: string
  noScroll?: boolean
}

export type ReportTabsProps = {
  activeTabId: string
  onTabChange: (tabId: string) => void
  tabs: ReportTab[]
}

export function ReportTabs({ activeTabId, onTabChange, tabs }: ReportTabsProps) {
  return (
    <nav aria-label="Report views" className="report-tabs">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId

        return (
          <button
            aria-current={isActive ? 'page' : undefined}
            className={`report-tab ${isActive ? 'report-tab--active' : ''}`}
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            type="button"
          >
            {tab.label}
          </button>
        )
      })}
    </nav>
  )
}
