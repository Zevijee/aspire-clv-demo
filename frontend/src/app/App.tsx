import { useState } from 'react'
import { LiveCensus } from '../features/census/components/LiveCensus'
import { CensusResidents } from '../features/census/components/CensusResidents'
import { ResidentsReport } from '../features/census/components/ResidentsReport'
import { Navigate, NavLink, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { AdmissionsLogs } from '../features/adt/components/AdmissionsLogs'
import { DischargesLogs } from '../features/adt/components/DischargesLogs'
import { DischargesOverview } from '../features/adt/components/DischargesOverview'
import { PayerChangesOverview } from '../features/adt/components/PayerChangesOverview'
import { PayerChangesLogs } from '../features/adt/components/PayerChangesLogs'
import { NetChangeOverview } from '../features/adt/components/NetChangeOverview'
import { MonthlyAdtTrending } from '../features/adt/components/MonthlyAdtTrending'
import { ReferringHospitalOverview } from '../features/adt/components/ReferringHospitalOverview'
import { NetChangeFilters } from '../features/adt/components/NetChangeFilters'
import { NetChangePayerFilter } from '../features/adt/components/NetChangePayerFilter'
import { AdmissionsPayerFilter } from '../features/adt/components/AdmissionsPayerFilter'
import { monthlyFilter } from '../features/adt/api/monthlyAdt'
import { PayerFilter } from '../features/adt/components/PayerFilter'
import { AdmissionsTesting } from '../features/adt/components/AdmissionsTesting'
import { analyticsModules, reports, reportsByModule } from '../features/navigation/reportCatalog'
import { useAccount } from '../features/auth/context'
import { UserSettings } from '../features/auth/UserSettings'
import { ReportDateRangeFilter } from '../shared/components/filters/ReportDateRangeFilter'
import { ReportMonthRangeFilter, getReportMonthRange } from '../shared/components/filters/ReportMonthRangeFilter'
import { AdmissionsOverviewFilters } from '../features/adt/components/AdmissionsOverviewFilters'
import type { OverviewSelection } from '../features/adt/utils/admissionsOverviewFilters'
import { DischargesFilters } from '../features/adt/components/DischargesFilters'
import type { DischargeSelection } from '../features/adt/components/DischargesOverview'
import { ReportFilters } from '../shared/components/filters/ReportFilters'
import { FilterDropdown } from '../shared/components/filters/FilterDropdown'
import { ReportLayout } from '../shared/components/layout/ReportLayout'
import type { AnalyticsModule } from '../shared/types/report'
import {
  getDefaultReportDateRange,
  formatReportDateRange,
} from '../shared/utils/reportDateRange'
import '../App.css'

const admissionsTabs = [
  { id: 'testing', label: 'Overview' },
  { id: 'logs', label: 'Logs', noScroll: true },
]
const dischargesTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'logs', label: 'Logs', noScroll: true },
]
const liveCensusTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'facilities', label: 'Facilities', noScroll: true },
  { id: 'residents', label: 'Residents', noScroll: true },
]
const monthlyTabs = [
  { id: 'admissions', label: 'Admissions' },
  { id: 'discharges', label: 'Discharges' },
  { id: 'net-change', label: 'Net Change' },
]

function ModuleIcon({ module }: { module: AnalyticsModule }) {
  if (module === 'ADT') {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="m8 3-4 4 4 4" />
        <path d="M4 7h16" />
        <path d="m16 21 4-4-4-4" />
        <path d="M20 17H4" />
      </svg>
    )
  }

  if (module === 'Census') {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M16 3.1a4 4 0 0 1 0 7.8" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.9" />
      </svg>
    )
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <rect width="8" height="4" x="8" y="2" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <path d="M12 11h4M12 16h4M8 11h.01M8 16h.01" />
    </svg>
  )
}

function App() {
  const { pathname } = useLocation()
  const account = useAccount()
  const [dischargeSelection, setDischargeSelection] = useState<DischargeSelection>({ scope: null, payers: [], destinations: [] })
  const [overviewSelection, setOverviewSelection] = useState<OverviewSelection>({ scope: null, payers: [], sources: [] })
  const [expandedModules, setExpandedModules] = useState<Set<AnalyticsModule>>(
    () => {
      const report = reports.find((report) => report.path === pathname)
      return new Set<AnalyticsModule>(report ? [report.module] : [])
    },
  )
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const isReportPage = reports.some((report) => report.path === pathname)
  const currentReport = reports.find((report) => report.path === pathname) ?? reports[0]
  const isAdmissionsReport = currentReport.path === '/adt/admissions'
  const isDischargesReport = currentReport.path === '/adt/discharges'
  const isPayerChangesReport = currentReport.path === '/adt/payer-changes'
  const isMonthlyAdtReport = currentReport.path === '/adt/monthly-trending'
  const [monthlyTab, setMonthlyTab] = useState(() => {
    try {
      const saved = localStorage.getItem('monthly-adt-tab')
      return monthlyTabs.find(tab => tab.id === saved)?.id ?? 'admissions'
    } catch { return 'admissions' }
  })
  const monthRange = getReportMonthRange(searchParams)
  const admissionsView = searchParams.get('view')
  const activeAdmissionsTab = admissionsTabs.find((tab) => tab.id === admissionsView)?.id ?? 'testing'
  const activeDischargesTab = dischargesTabs.find((tab) => tab.id === admissionsView)?.id ?? 'overview'
  const activeLiveCensusTab = admissionsView === 'facilities' || admissionsView === 'residents'
    ? admissionsView : 'overview'
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate

  function handleAdmissionsTabChange(tabId: string) {
    const nextSearchParams = new URLSearchParams(searchParams)

    if (tabId === 'testing') {
      nextSearchParams.delete('view')
    } else {
      nextSearchParams.set('view', tabId)
    }

    setSearchParams(nextSearchParams)
  }

  return (
    <div className="app-shell">
      {isMobileMenuOpen && (
        <button
          className="navigation-scrim"
          type="button"
          aria-label="Close navigation"
          onClick={() => setIsMobileMenuOpen(false)}
        />
      )}
      <aside
        id="primary-navigation"
        className={`sidebar ${isMobileMenuOpen ? 'sidebar--open' : ''}`}
        aria-label="Primary navigation"
      >
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 64 64">
              <path d="M45.5 19.3A18.2 18.2 0 1 0 45.5 44L41 39.5a11.8 11.8 0 1 1 0-15.1Z" />
            </svg>
          </span>
          <span className="brand-copy">
            <strong>Clearview</strong>
            <small>Aspire Health Group</small>
          </span>
        </div>

        <nav className="module-navigation" aria-label="Analytics modules">
          {analyticsModules.map((module) => {
            const isExpanded = expandedModules.has(module)

            return (
              <section className="module-group" key={module}>
                <button
                  type="button"
                  className="module-trigger"
                  aria-expanded={isExpanded}
                  onClick={() => {
                    setExpandedModules((currentModules) => {
                      const nextModules = new Set(currentModules)

                      if (nextModules.has(module)) {
                        nextModules.delete(module)
                      } else {
                        nextModules.add(module)
                      }

                      return nextModules
                    })
                  }}
                >
                  <span className="module-label">
                    <ModuleIcon module={module} />
                    <span>{module}</span>
                  </span>
                  <svg aria-hidden="true" viewBox="0 0 16 16">
                    <path d="m4 6 4 4 4-4" />
                  </svg>
                </button>
                {isExpanded && (
                  <div>
                    {reportsByModule[module].map((report) => (
                      <NavLink
                        className={({ isActive }) =>
                          `report-link ${isActive ? 'report-link--active' : ''}`
                        }
                        key={report.path}
                        onClick={() => {
                          setIsMobileMenuOpen(false)
                        }}
                        to={report.path}
                      >
                        {report.title}
                      </NavLink>
                    ))}
                  </div>
                )}
              </section>
            )
          })}
        </nav>

        <div className="sidebar-account">
          <NavLink to="/settings" onClick={() => setIsMobileMenuOpen(false)}
            className={({ isActive }) => `sidebar-account__settings ${isActive ? 'sidebar-account__settings--active' : ''}`}>
            <span className="sidebar-account__avatar" aria-hidden="true">{account.username.slice(0, 1)}</span>
            <span className="sidebar-account__copy">
              <strong>{account.username}</strong>
              <small>User settings</small>
            </span>
          </NavLink>
          <button type="button" className="sidebar-account__sign-out" aria-label="Sign out" title="Sign out"
            onClick={account.signOut}>
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="m16 17 5-5-5-5" />
              <path d="M21 12H9" />
            </svg>
          </button>
        </div>
      </aside>

      {pathname === '/settings' ? (
        <ReportLayout
          title="User settings"
          leadingControl={
            <button
              className="mobile-menu-button"
              type="button"
              aria-label="Open navigation"
              aria-expanded={isMobileMenuOpen}
              aria-controls="primary-navigation"
              onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
            >
              <span /><span /><span />
            </button>
          }
        >
          <UserSettings />
        </ReportLayout>
      ) : !isReportPage ? (
        <ReportLayout
          title="Clearview"
          titleDetail="Select a report from the navigation to get started."
          leadingControl={
            <button
              className="mobile-menu-button"
              type="button"
              aria-label="Open navigation"
              aria-expanded={isMobileMenuOpen}
              aria-controls="primary-navigation"
              onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
            >
              <span /><span /><span />
            </button>
          }
        >
          {pathname !== '/' && <Navigate replace to="/" />}
        </ReportLayout>
      ) : (
      <ReportLayout
        internalScroll={currentReport.path === '/adt/referring-hospital' || currentReport.path === '/census/residents'}
        filters={
          <ReportFilters>
            {isAdmissionsReport && <AdmissionsPayerFilter
              values={activeAdmissionsTab === 'logs' ? searchParams.getAll('logs_payer') : overviewSelection.payers}
              onChange={payers => {
                if (activeAdmissionsTab !== 'logs') {
                  setOverviewSelection(current => ({ ...current, payers }))
                  return
                }
                const next = new URLSearchParams(searchParams)
                next.delete('logs_payer')
                payers.forEach(payer => next.append('logs_payer', payer))
                setSearchParams(next)
              }} />}
            {isDischargesReport && <PayerFilter displayValues
              values={activeDischargesTab === 'logs' ? searchParams.getAll('logs_payer_type') : dischargeSelection.payers}
              onChange={payers => {
                if (activeDischargesTab !== 'logs') {
                  setDischargeSelection(current => ({ ...current, payers }))
                  return
                }
                const next = new URLSearchParams(searchParams)
                next.delete('logs_payer_type')
                payers.forEach(payer => next.append('logs_payer_type', payer))
                setSearchParams(next)
              }} />}
            {isAdmissionsReport && <FilterDropdown label="Source type" placeholder="All sources"
              options={['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility', 'Assisted Living', 'Community'].map(value => ({ value, label: value }))}
              values={activeAdmissionsTab === 'logs' ? searchParams.getAll('logs_source-type') : overviewSelection.sources}
              onChange={sources => {
                if (activeAdmissionsTab !== 'logs') {
                  setOverviewSelection(current => ({ ...current, sources }))
                  return
                }
                const next = new URLSearchParams(searchParams)
                next.delete('logs_source-type')
                sources.forEach(source => next.append('logs_source-type', source))
                setSearchParams(next)
              }} />}
            {isDischargesReport && <FilterDropdown label="Destination type" placeholder="All destinations"
              options={['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility', 'Assisted Living', 'Hospice', 'Funeral Home'].map(value => ({ value, label: value }))}
              values={activeDischargesTab === 'logs' ? searchParams.getAll('logs_destination_type') : dischargeSelection.destinations}
              onChange={destinations => {
                if (activeDischargesTab !== 'logs') {
                  setDischargeSelection(current => ({ ...current, destinations }))
                  return
                }
                const next = new URLSearchParams(searchParams)
                next.delete('logs_destination_type')
                destinations.forEach(destination => next.append('logs_destination_type', destination))
                setSearchParams(next)
              }} />}
            {currentReport.path === '/adt/net-change' && <NetChangePayerFilter />}
            {currentReport.path === '/adt/referring-hospital' && <AdmissionsPayerFilter values={searchParams.getAll('referring_payer')}
              onChange={payers => {
                const next = new URLSearchParams(searchParams)
                next.delete('referring_payer')
                payers.forEach(payer => next.append('referring_payer', payer))
                setSearchParams(next)
              }} />}
            {isMonthlyAdtReport && <PayerFilter values={searchParams.getAll('monthly_payer')}
              onChange={payers => {
                const next = new URLSearchParams(searchParams)
                next.delete('monthly_payer')
                payers.forEach(payer => next.append('monthly_payer', payer))
                setSearchParams(next)
              }} />}
            {/* Only the admissions and discharges views have a source or destination.
                Net change reads census, which is a level and does not divide by
                where a resident came from or went to. */}
            {isMonthlyAdtReport && monthlyTab in monthlyFilter && (() => {
              const filter = monthlyFilter[monthlyTab as keyof typeof monthlyFilter]
              return <FilterDropdown label={filter.label} placeholder={filter.placeholder}
                options={filter.options.map(value => ({ value, label: value }))}
                values={searchParams.getAll(filter.search)}
                onChange={values => {
                  const next = new URLSearchParams(searchParams)
                  next.delete(filter.search)
                  values.forEach(value => next.append(filter.search, value))
                  setSearchParams(next)
                }} />
            })()}
            {isMonthlyAdtReport ? <ReportMonthRangeFilter /> : currentReport.path !== '/adt/referring-hospital' && currentReport.path !== '/census/daily-census'
              && currentReport.path !== '/census/residents' ? <ReportDateRangeFilter /> : null}
          </ReportFilters>
        }
        tabFilters={
          isAdmissionsReport && activeAdmissionsTab === 'testing' ? (
            <AdmissionsOverviewFilters selection={overviewSelection} onChange={setOverviewSelection} />
          ) : isDischargesReport ? (
            <DischargesFilters logs={activeDischargesTab === 'logs'} selection={dischargeSelection} onChange={setDischargeSelection} />
          ) : currentReport.path === '/adt/net-change' ? <NetChangeFilters /> : undefined
        }
        tabs={
          isAdmissionsReport
            ? {
                  activeTabId: activeAdmissionsTab,
                  onTabChange: handleAdmissionsTabChange,
                  tabs: admissionsTabs,
              }
            : isDischargesReport || isPayerChangesReport ? {
                activeTabId: activeDischargesTab,
                onTabChange: handleAdmissionsTabChange,
                tabs: dischargesTabs,
              } : currentReport.path === '/census/daily-census' ? {
                activeTabId: activeLiveCensusTab,
                tabs: liveCensusTabs,
                onTabChange: (id: string) => {
                  const next = new URLSearchParams(searchParams)
                  if (id === 'overview') next.delete('view')
                  else next.set('view', id)
                  setSearchParams(next)
                },
              } : isMonthlyAdtReport ? {
                activeTabId: monthlyTab,
                tabs: monthlyTabs,
                onTabChange: (id: string) => {
                  setMonthlyTab(id)
                  try { localStorage.setItem('monthly-adt-tab', id) } catch { /* Keep selection in memory when storage is unavailable. */ }
                  // Drop the other views' filters. A source selection left in the
                  // URL while looking at discharges would read as an active
                  // filter that narrows nothing.
                  const next = new URLSearchParams(searchParams)
                  let changed = false
                  for (const [key, value] of Object.entries(monthlyFilter)) {
                    if (key !== id && next.has(value.search)) { next.delete(value.search); changed = true }
                  }
                  if (changed) setSearchParams(next)
                },
              } : undefined
        }
        title={currentReport.title}
        titleDetail={currentReport.path === '/census/daily-census' ? 'Current census' : currentReport.path === '/census/residents' ? 'Every resident ever admitted' : currentReport.path === '/adt/referring-hospital' ? 'Last 3 complete years · Monthly referral performance' : isMonthlyAdtReport
          ? `${monthRange.start.format('MMMM YYYY')} to ${monthRange.end.format('MMMM YYYY')} (${monthRange.end.diff(monthRange.start, 'month') + 1} months)`
          : formatReportDateRange(startDate, endDate)}
        leadingControl={
          <button
            className="mobile-menu-button"
            type="button"
            aria-label="Open navigation"
            aria-expanded={isMobileMenuOpen}
            aria-controls="primary-navigation"
            onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
          >
            <span />
            <span />
            <span />
          </button>
        }
      >
        <Routes>
          {reports.map((report) => (
            <Route
              element={
                report.path === '/census/residents' ? <ResidentsReport /> : report.path === '/census/daily-census' ? (
                  activeLiveCensusTab === 'residents' ? <CensusResidents /> : <LiveCensus view={activeLiveCensusTab} />
                ) : report.path === '/adt/admissions' ? (
                  activeAdmissionsTab === 'logs' ? (
                    <AdmissionsLogs />

                  ) : (
                    <AdmissionsTesting selection={overviewSelection} onChangeSelection={setOverviewSelection} />
                  )
                ) : report.path === '/adt/discharges' ? (
                  activeDischargesTab === 'logs' ? <DischargesLogs />
                    : <DischargesOverview selection={dischargeSelection} onChange={setDischargeSelection} />
                ) : report.path === '/adt/referring-hospital' ? (
                  <ReferringHospitalOverview />
                ) : report.path === '/adt/monthly-trending' ? (
                  <MonthlyAdtTrending activeTab={monthlyTab} />
                ) : report.path === '/adt/net-change' ? (
                  <NetChangeOverview />
                ) : report.path === '/adt/payer-changes' ? (
                  activeDischargesTab === 'logs' ? <PayerChangesLogs /> : <PayerChangesOverview />
                ) : (
                  <section className="report-placeholder" aria-label={`${report.title} content`} />
                )
              }
              key={report.path}
              path={report.path}
            />
          ))}
          <Route element={<Navigate replace to="/" />} path="/" />
          <Route element={<Navigate replace to="/" />} path="*" />
        </Routes>
      </ReportLayout>
      )}
    </div>
  )
}

export default App
