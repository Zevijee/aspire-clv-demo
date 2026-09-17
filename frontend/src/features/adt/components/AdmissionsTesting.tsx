import { useMemo, useState } from 'react'
import { useReportSearchParams as useSearchParams } from '../../../shared/components/ReportSearchContext'
import dayjs from 'dayjs'

import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownNavigation, type DrilldownBreadcrumb } from '../../../shared/components/DrilldownNavigation'
import { getDefaultReportDateRange } from '../../../shared/utils/reportDateRange'
import { getAdmissionLogsParams } from '../utils/admissionsLogNavigation'
import { useAdmissionsDrilldownData } from '../hooks/useAdmissionsDrilldownData'
import {
  getDrilldownRows,
  getDrilldownTotal,
  getDrilldownRowScope,
  type DrilldownRow,
  type DrilldownScope,
} from '../utils/admissionsDrilldown'
import { AdmissionsDailyTrend } from './AdmissionsDailyTrend'
import { LineChart } from '../../../shared/components/charts/LineChart'
import { AdmissionsPayerDistribution } from './AdmissionsPayerDistribution'
import { AdmissionsSourceTypeDistribution } from './AdmissionsSourceTypeDistribution'
import { BarChartRanking } from '../../../shared/components/charts/BarChartRanking'
import { ReferringHospitalsModal, type HospitalSelection } from './ReferringHospitalsModal'
import { getLocationLevel, groupOverviewFacilities, selectedOverviewFacilities, type OverviewSelection } from '../utils/admissionsOverviewFilters'

export function AdmissionsTesting({ selection, onChangeSelection }: {
  selection: OverviewSelection
  onChangeSelection: (selection: OverviewSelection) => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultRange = getDefaultReportDateRange()
  const startDate = searchParams.get('start_date') ?? defaultRange.startDate
  const endDate = searchParams.get('end_date') ?? defaultRange.endDate
  const { scope, payers: selectedPayers, sources: selectedSources } = selection
  const setScope = (scope: DrilldownScope) => onChangeSelection({ ...selection, scope })
  const setSelectedPayers = (payers: string[]) => onChangeSelection({ ...selection, payers })
  const setSelectedSources = (sources: string[]) => onChangeSelection({ ...selection, sources })
  const [hospitalSelection, setHospitalSelection] = useState<HospitalSelection | null>(null)
  const results = useAdmissionsDrilldownData(startDate, endDate, selectedPayers, selectedSources)
  const customLevel = selection.groupBy ?? getLocationLevel(selection.locations ?? [])
  const days = dayjs(endDate).diff(dayjs(startDate), 'day') + 1
  const customFacilities = useMemo(() => selectedOverviewFacilities(results.facilities.rows, selection.locations ?? [], scope), [results.facilities.rows, selection.locations, scope])
  const level = scope === null ? customLevel ?? 'state' : scope.portfolio === undefined ? 'portfolio' : scope.region === undefined ? 'region' : scope.facility === undefined ? 'facility' : 'facility-detail'
  const plural = level === 'state' ? 'States' : level === 'portfolio' ? 'Portfolios' : level === 'region' ? 'Regions' : level === 'facility' ? 'Facilities' : 'Facility detail'
  const status = customLevel ? results.facilities : level === 'state' || level === 'portfolio' ? results.portfolios : level === 'region' ? results.regions : results.facilities
  const rows = customLevel ? groupOverviewFacilities(customFacilities, level === 'facility-detail' ? 'facility' : level, days) : getDrilldownRows({
    portfolios: results.portfolios.rows,
    regions: results.regions.rows,
    facilities: results.facilities.rows,
  }, scope)
  const sourceFilters = useMemo(() => ({
    facilities: customLevel ? customFacilities.length ? customFacilities.map((row) => row.facility_name) : ['__no_matching_locations__'] : scope?.facility !== undefined ? [scope.facility] : [],
    payerTypes: selectedPayers,
    portfolios: scope?.portfolio !== undefined ? [scope.portfolio]
      : scope !== null ? results.portfolios.rows.filter((row) => row.state === scope.state).map((row) => row.region) : [],
    regions: scope?.region !== undefined ? [scope.region] : [],
  }), [scope, results.portfolios.rows, selectedPayers, customLevel, customFacilities])
  const reportFilters = useMemo(() => ({ ...sourceFilters, sourceTypes: selectedSources }), [sourceFilters, selectedSources])
  const sourceBlocked = customLevel ? results.facilities.loading || !!results.facilities.error : scope !== null && scope.portfolio === undefined && (results.portfolios.loading || !!results.portfolios.error || sourceFilters.portfolios.length === 0)
  const title = level === 'state' ? 'State Admissions Metrics' : level === 'portfolio' ? 'Portfolio Admissions Metrics' : level === 'region' ? 'Region performance' : level === 'facility' ? 'Facility performance' : 'Facility admissions metrics'
  const scopeName = scope?.facility ?? scope?.region ?? scope?.portfolio ?? scope?.state ?? (customLevel ? `${selection.locations?.length ? selection.locations.length + ' selected' : 'All'} ${customLevel === 'facility' ? 'facilities' : customLevel + 's'}` : 'All states')

  function navigate(nextScope: DrilldownScope) {
    setScope(nextScope)
  }

  const clearCustomView = () => onChangeSelection({ ...selection, scope: null, locations: [], groupBy: 'state' })
  const breadcrumbs: DrilldownBreadcrumb[] = []
  if (scope !== null) {
    breadcrumbs.push({
      id: JSON.stringify(['state', scope.state]), label: scope.state,
      onSelect: () => navigate({ state: scope.state }),
    })
    if (scope.portfolio !== undefined) {
      breadcrumbs.push({
        id: JSON.stringify(['portfolio', scope.state, scope.portfolio]), label: scope.portfolio,
        onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio }),
      })
    }
    if (scope.region !== undefined) {
      breadcrumbs.push({
        id: JSON.stringify(['region', scope.state, scope.portfolio, scope.region]), label: scope.region,
        onSelect: () => navigate({ state: scope.state, portfolio: scope.portfolio, region: scope.region }),
      })
    }
  }

  if (scope?.facility !== undefined) {
    breadcrumbs.push({
      id: JSON.stringify(['facility', scope.state, scope.portfolio, scope.region, scope.facility]),
      label: scope.facility,
    })
  }

  function drillInto(row: DrilldownRow) {
    if (level === 'state') {
      navigate({ state: row.state })
      return
    }
    navigate({ state: row.state, portfolio: row.portfolio,
      ...((level === 'region' || level === 'facility') && row.region !== null ? { region: row.region } : {}),
      ...(level === 'facility' ? { facility: row.name } : {}),
    })
  }

  const nameColumn: TableColumn<DrilldownRow> = {
      id: 'name',
      header: level === 'state' ? 'State' : level === 'portfolio' ? 'Portfolio' : level === 'region' ? 'Region' : 'Facility',
      isRowHeader: true,
      value: (row) => row.name,
      format: (_, row) => {
        const name = <span className="admissions-explorer__entity"><strong>{row.name}</strong></span>
        return row.isTotal || level === 'facility-detail' ? name : (
          <button aria-label={level === 'facility' ? `View admissions for ${row.name}` : `View ${level === 'state' ? 'portfolios' : level === 'portfolio' ? 'regions' : 'facilities'} in ${row.name}`}
            className="admissions-explorer__drill" onClick={() => drillInto(row)} type="button">
            {name}
          </button>
        )
      },
    }

  const metricColumns: TableColumn<DrilldownRow>[] = [
    nameColumn,
    { id: 'current', header: 'Total admissions', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.current, format: (value, row) => (
        <button type="button" className="admissions-explorer__drill admissions-explorer__drill--count"
          aria-label={`View ${value.toLocaleString()} admissions in Logs for ${row.isTotal ? scopeName : row.name}`}
          onClick={() => setSearchParams(getAdmissionLogsParams(
            searchParams, row, scope, startDate, endDate, selectedPayers, selectedSources,
          ))}>
          {value.toLocaleString()}
        </button>
      ) },
    { id: 'readmissions', header: 'Readmissions', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.readmissions, format: (value, row) => (
        <button type="button" className="admissions-explorer__drill admissions-explorer__drill--count"
          aria-label={`View ${value.toLocaleString()} readmissions in Logs for ${row.isTotal ? scopeName : row.name}`}
          onClick={() => setSearchParams(getAdmissionLogsParams(
            searchParams, row, scope, startDate, endDate, selectedPayers, selectedSources, true,
          ))}>
          {value.toLocaleString()}
        </button>
      ) },
    { id: 'prior', header: 'Prior-period admissions', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.prior, format: (value) => value.toLocaleString() },
    { id: 'change', header: 'Admissions vs Prior', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.change, change: { favorable: 'increase' } },
    { id: 'referring-hospitals', header: 'Referring hospitals', numeric: true, initialSortDirection: 'descending',
      value: (row) => row.referringHospitals.length, format: (value, row) => (
        <button type="button" className="admissions-explorer__drill admissions-explorer__drill--count"
          aria-haspopup="dialog"
          aria-label={`View ${value.toLocaleString()} referring hospitals for ${row.isTotal ? scopeName : row.name}`}
          onClick={() => setHospitalSelection({
            facilities: row.facilityNames,
            scope: getDrilldownRowScope(row, scope), label: row.isTotal ? scopeName : row.name,
            startDate, endDate, payers: selectedPayers, sourceTypes: selectedSources,
          })}>
          {value.toLocaleString()}
        </button>
      ) },
  ]
  const columns = metricColumns

  return (
    <>
      <ReferringHospitalsModal selection={hospitalSelection} onClose={() => setHospitalSelection(null)} />
      <DrilldownNavigation
        ariaLabel="Admissions drill-down"
        locationView={{ groupBy: customLevel ?? 'state', selectedCount: selection.locations?.length ?? 0,
          selectionLevel: getLocationLevel(selection.locations ?? []),
          onReturn: () => navigate(null), onClear: clearCustomView }}
        activeFilters={[
          ...(selectedPayers.length ? ['payer'] : []),
          ...(selectedSources.length ? ['source'] : []),
        ]}
        onClearFilter={(filter) => { if (filter === 'payer') setSelectedPayers([]); if (filter === 'source') setSelectedSources([]) }}
        items={breadcrumbs}
      />

      <Table key={JSON.stringify([scope, selection.locations, selection.groupBy])}
        initialSort={{ columnId: 'current', direction: 'descending' }}
        loading={status.loading} error={status.error} onRetry={status.onRetry}
        columns={columns} rows={rows} getRowKey={(row) => row.key}
        getFooterRow={(visibleRows) => getDrilldownTotal(visibleRows, days)}
        title={title}
        subtitle={`${scopeName} · ${level === 'state' ? 'Select a state to explore its portfolios.' : level === 'portfolio' ? 'Select a portfolio to explore its regions.' : level === 'region' ? 'Select a region to explore its facilities.' : level === 'facility' ? 'Select a facility to view its admissions.' : 'Metrics and charts for this facility only.'}`}
        csvFileName={`admissions-${plural.toLowerCase()}-${scopeName}-${startDate}-to-${endDate}.csv`}
        emptyMessage="No locations match this view. Choose another date range or return to All states."
      />
      <div className="admissions-dashboard">
      {sourceBlocked ? (
        <BarChartRanking title="Admissions by Source Type" subtitle="Admissions by source type"
          categoryLabel="Admission source type" valueLabel="Admissions" items={[]}
          loading={status.loading} error={status.error} onRetry={status.onRetry} />
      ) : <AdmissionsSourceTypeDistribution filters={sourceFilters} selectedSources={selectedSources} onChangeSources={setSelectedSources} />}
      <AdmissionsPayerDistribution startDate={startDate} endDate={endDate} scope={scope}
        locations={selection.locations} sourceTypes={selectedSources} selectedPayers={selectedPayers} onChangePayers={setSelectedPayers} />
      </div>
      {sourceBlocked ? (
        <LineChart title="Daily Admissions" items={[]}
          loading={status.loading} error={status.error} onRetry={status.onRetry} />
      ) : <AdmissionsDailyTrend filters={reportFilters} />}
    </>
  )
}
