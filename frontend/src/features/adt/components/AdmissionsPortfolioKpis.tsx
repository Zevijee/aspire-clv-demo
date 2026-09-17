import type { DataStateProps } from '../../../shared/components/DataState'
import { Kpis, type KpiItem, type KpiTrend } from '../../../shared/components/Kpis'
import type { RegionAdmissionsMetrics } from '../api/admissions'

function trend(change: number, value: string, label: string): KpiTrend {
  return {
    direction: change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
    tone: change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral',
    value,
    label,
  }
}

function signed(value: number, digits = 0) {
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
    signDisplay: 'exceptZero',
  })
}

export function AdmissionsPortfolioKpis({ rows, ...status }: DataStateProps & { rows: RegionAdmissionsMetrics[] }) {
  const ranked = rows
    .filter((row) => row.prior_period_admissions > 0)
    .map((row) => ({
      ...row,
      growth: ((row.total_admissions - row.prior_period_admissions) / row.prior_period_admissions) * 100,
    }))
    .sort((a, b) => b.growth - a.growth || a.region.localeCompare(b.region))
  const current = rows.reduce((sum, row) => sum + row.total_admissions, 0)
  const prior = rows.reduce((sum, row) => sum + row.prior_period_admissions, 0)
  const growing = rows.filter((row) => row.total_admissions > row.prior_period_admissions).length

  function rankingItem(header: string, row: (typeof ranked)[number] | undefined): KpiItem {
    if (!row) {
      return { header, value: '—', trend: trend(0, '', 'No portfolios with prior admissions') }
    }
    const ties = ranked.filter((candidate) => candidate.growth === row.growth).length
    return {
      header,
      value: `${signed(row.growth, 1)}%`,
      trend: trend(row.growth, '', `${row.region}${ties > 1 ? ` (tied with ${ties - 1} other${ties > 2 ? 's' : ''})` : ''}`),
    }
  }

  return (
    <>
      <Kpis {...status} items={[
        rankingItem('Best performer vs prior', ranked[0]),
        rankingItem('Worst performer vs prior', ranked[ranked.length - 1]),
        {
          header: 'Net admissions change',
          value: rows.length ? signed(current - prior) : '—',
          trend: trend(current - prior, prior > 0 ? `${signed(((current - prior) / prior) * 100, 1)}%` : '',
            prior > 0 ? 'vs prior period across all portfolios' : 'Percentage unavailable: no prior admissions'),
        },
        {
          header: 'Portfolios growing',
          value: rows.length ? `${growing} / ${rows.length}` : '—',
          trend: trend(0, '', 'With more admissions than the prior period'),
        },
      ]} />
    </>
  )
}
