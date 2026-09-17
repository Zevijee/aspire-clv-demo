import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { DrilldownTable } from '../../../shared/components/DrilldownTable'
import { DrilldownNavigation } from '../../../shared/components/DrilldownNavigation'
import { InfoDisclosure } from '../../../shared/components/InfoDisclosure'

type Location = { facility_code: string; state: string; portfolio: string; region: string; facility: string }
type Data = { locations: Location[]; items: { facility_code: string; hospital: string; recent: number; baseline: number }[] }
const levels = ['state', 'portfolio', 'region', 'facility'] as const
const labels = ['State', 'Portfolio', 'Region', 'Facility']
const categories = ['Strong growth', 'Growing', 'Slight growth', 'Stable', 'Slight decline', 'Declining', 'Sharp decline', 'New/returning']
const thresholds = ['At least +20%', '+10% to under +20%', '+5% to under +10%', 'Between -5% and +5%', '-5% to above -10%', '-10% to above -20%', '-20% or lower', 'Recent referrals with none in the baseline period']
type Row = { name: string; hospitals: Map<string, { recent: number; baseline: number }>; counts: number[]; isTotal?: boolean }
function performanceCategory(recent: number, baseline: number) {
  const delta = (recent * 8 - baseline) * 100
  return !baseline ? 7 : delta >= 20 * baseline ? 0 : delta >= 10 * baseline ? 1
    : delta >= 5 * baseline ? 2 : delta > -5 * baseline ? 3 : delta > -10 * baseline ? 4
    : delta > -20 * baseline ? 5 : 6
}

export function HospitalPerformanceLocations() {
  const [params] = useSearchParams()
  const [path, setPath] = useState<string[]>([])
  const [retry, setRetry] = useState(0)
  const request = new URLSearchParams()
  params.getAll('referring_payer').forEach(value => request.append('payer_type', value))
  params.getAll('referring_facility').forEach(value => request.append('facility', value))
  const query = request.toString()
  const key = JSON.stringify([query, retry])
  const [response, setResponse] = useState<{ key: string; data?: Data; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/api/v1/adt/admissions/referring-hospital-location-performance?${query}`, { signal: controller.signal })
      .then(async result => {
        if (!result.ok) throw new Error('Hospital performance could not load. Please try again.')
        return await result.json() as Data
      }).then(data => { if (!controller.signal.aborted) setResponse({ key, data }) })
      .catch((error: Error) => { if (!controller.signal.aborted) setResponse({ key, error: error.message }) })
    return () => controller.abort()
  }, [query, key])
  const result = response?.key === key ? response : null
  const depth = Math.min(path.length, 3)
  const groups = new Map<string, Row>()
  const facilityGroups = new Map<string, Row>()
  for (const location of result?.data?.locations ?? []) {
    if (!path.every((value, index) => location[levels[index]] === value)) continue
    const name = location[levels[depth]]
    const row = groups.get(name) ?? { name, hospitals: new Map(), counts: Array(8).fill(0) }
    groups.set(name, row)
    facilityGroups.set(location.facility_code, row)
  }
  for (const item of result?.data?.items ?? []) {
    const row = facilityGroups.get(item.facility_code)
    if (!row) continue
    const hospital = row.hospitals.get(item.hospital) ?? { recent: 0, baseline: 0 }
    hospital.recent += item.recent
    hospital.baseline += item.baseline
    row.hospitals.set(item.hospital, hospital)
  }
  function rank(row: Row) {
    for (const hospital of row.hospitals.values()) {
    // Compare monthly rates: recent/3 against baseline/24, using integer thresholds.
    const category = performanceCategory(hospital.recent, hospital.baseline)
    row.counts[category]++
    }
    return row
  }
  for (const row of groups.values()) rank(row)
  function totalRows(rows: Row[]): Row {
    const total: Row = { name: 'Total', isTotal: true, hospitals: new Map(), counts: Array(8).fill(0) }
    for (const row of rows) for (const [name, values] of row.hospitals) {
      const combined = total.hospitals.get(name) ?? { recent: 0, baseline: 0 }
      combined.recent += values.recent
      combined.baseline += values.baseline
      total.hospitals.set(name, combined)
    }
    return rank(total)
  }
  const columns: TableColumn<Row>[] = [
    { id: 'location', header: labels[depth], isRowHeader: true, value: row => row.name,
      format: (_, row) => row.isTotal || path.length === 4 ? row.name : <button type="button" className="drilldown-table__link"
        onClick={() => setPath([...path, row.name])}>{row.name}</button> },
    { id: 'total', header: 'Hospitals', numeric: true, value: row => row.hospitals.size },
    ...categories.map((header, index): TableColumn<Row> => ({ id: `category_${index}`, header,
      numeric: true, value: row => row.counts[index], format: value => <span title={thresholds[index]}
        className={index < 3 ? 'report-table__change--favorable' : index > 3 && index < 7 ? 'report-table__change--adverse' : undefined}>
        {Number(value).toLocaleString()}</span> })),
  ]
  const hospitalRows = [...totalRows([...groups.values()]).hospitals].map(([name, values]) => ({
    name, recent: values.recent / 3, usual: values.baseline / 24,
    difference: values.recent / 3 - values.baseline / 24,
    percentage: values.baseline ? (values.recent * 8 - values.baseline) / values.baseline * 100 : 0,
    category: performanceCategory(values.recent, values.baseline),
  }))
  const hospitalColumns: TableColumn<(typeof hospitalRows)[number]>[] = [
    { id: 'name', header: 'Hospital', isRowHeader: true, value: row => row.name },
    { id: 'performance', header: 'Performance', value: row => categories[row.category] },
    { id: 'recent', header: 'Recent avg/month', numeric: true, value: row => row.recent,
      format: value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) },
    { id: 'usual', header: 'Usual avg/month', numeric: true, value: row => row.usual,
      format: value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) },
    { id: 'difference', header: 'Change/month', numeric: true, value: row => row.difference,
      change: { favorable: 'increase' },
      format: value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1, signDisplay: 'exceptZero' }) },
    { id: 'percentage', header: 'Change %', numeric: true, value: row => row.percentage,
      change: { favorable: 'increase' },
      format: value => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1, signDisplay: 'exceptZero' })}%` },
  ]
  return <div className="hospital-performance-locations">
    <DrilldownNavigation items={[{ id: 'root', label: 'All states', onSelect: () => setPath([]) },
      ...path.map((label, index) => ({ id: String(index), label, onSelect: () => setPath(path.slice(0, index + 1)) }))]}
      level={{ current: depth + 1, total: 4, label: labels[depth] }} />
    <DrilldownTable title="Hospital performance by location"
      subtitle="Distinct hospitals by change in monthly referrals: last 3 complete months versus the preceding 24."
      columns={columns} rows={[...groups.values()]} getRowKey={row => row.name}
      getFooterRow={totalRows}
      stickyFirstColumn initialSort={{ columnId: 'total', direction: 'descending' }}
      loading={!result} error={result?.error} onRetry={() => setRetry(value => value + 1)}
      emptyMessage="No hospital performance data for the selected locations and payers."
      csvFileName="hospital-performance-by-location.csv" />
    <InfoDisclosure label="How performance is ranked" collapsible>
      <p>We compare average monthly hospital referrals over the last 3 complete months with the average
        over the preceding 24 months. Months with no referrals count as zero; the current partial month is excluded.</p>
      <p>Change = (recent monthly average − previous monthly average) ÷ previous monthly average × 100.</p>
      <ul>{categories.map((category, index) => <li key={category}><strong>{category}:</strong> {thresholds[index]}</li>)}</ul>
      <p>Each hospital is counted once per location row. Referrals to facilities within that location are combined
        before ranking, so a hospital’s category may differ between locations. Payer and facility filters apply to both periods.</p>
      <p>Hospitals with no referrals in either comparison period are excluded. New/returning hospitals are listed
        separately because a percentage change cannot be calculated from zero. Categories reflect percentage change,
        without a minimum volume requirement.</p>
    </InfoDisclosure>
    {(['declining', 'growing'] as const).map(direction => <Table key={direction}
      title={direction === 'declining' ? 'Declining hospitals' : 'Growing hospitals'}
      subtitle={`${path.at(-1) ?? 'All locations'}: recent monthly referrals compared with the preceding 24-month average.`}
      columns={hospitalColumns} rows={hospitalRows.filter(row => direction === 'declining'
        ? row.category >= 4 && row.category <= 6 : row.category <= 2)}
      getRowKey={row => row.name} searchable stickyFirstColumn
      initialSort={{ columnId: 'difference', direction: direction === 'declining' ? 'ascending' : 'descending' }}
      loading={!result} error={result?.error} onRetry={() => setRetry(value => value + 1)}
      emptyMessage={`No ${direction} hospitals for this location and these filters.`}
      csvFileName={`${direction}-hospitals.csv`} />)}

  </div>
}
