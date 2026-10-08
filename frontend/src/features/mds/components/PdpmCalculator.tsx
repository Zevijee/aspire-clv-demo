import { useEffect, useId, useState, type ReactNode } from 'react'
import { DataState } from '../../../shared/components/DataState'
import { FilterSelect } from '../../../shared/components/filters/FilterSelect'
import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { OpenViewButton } from '../../../shared/components/OpenViewButton'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import {
  getCalculatorFacilities, getPdpmCalculation, type CalculatorFacility, type PdpmCalculation,
} from '../api'

const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
const wholeMoney = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
// Four letters, PT/OT A-P, SLP A-L, nursing A-Y, NTA A-F; a fifth, the HIPPS
// assessment indicator, is allowed and ignored.
const CODE = /^[A-P][A-L][A-Y][A-F][0-9A-Z]?$/
const EXAMPLE_CODE = 'CBCB'
// The baseline and up to two codes against it, each in its own colour: its
// chip and its column share it, so a number is matched to its code at a glance.
const CODE_COLORS = ['var(--color-chart-series-primary)', 'var(--color-chart-series-tertiary)',
  'var(--color-chart-series-quinary)']
const MAX_CODES = CODE_COLORS.length
const LETTERS = ['PT/OT', 'SLP', 'Nursing', 'NTA']

type Calculation = PdpmCalculation
type Phase = Calculation['phases'][number]

/** Why a box's code is not priced yet, or null when it is fine. */
function problem(box: string) {
  if (!box) return null
  if (box.length < 4) return 'Needs four letters'
  if (!CODE.test(box)) {
    const ranges = ['A-P', 'A-L', 'A-Y', 'A-F']
    const at = [...box.slice(0, 4)].findIndex((letter, index) =>
      !new RegExp(`^[${ranges[index]}]$`).test(letter))
    return at >= 0 ? `${LETTERS[at]} letter must be ${ranges[at]}` : 'Not a PDPM code'
  }
  return null
}

/** A compared value's difference from the baseline. More revenue reads green. */
function Difference({ value, base, cents = false }: { value: number; base: number; cents?: boolean }) {
  const change = value - base
  if (Math.abs(change) < 0.005) return <span className="pdpm-calc__difference">Same as baseline</span>
  const sign = change > 0 ? '+' : '−'
  const amount = cents ? money(Math.abs(change)) : wholeMoney(Math.abs(change))
  return <span className={`pdpm-calc__difference pdpm-calc__difference--${change > 0 ? 'up' : 'down'}`}>
    {sign}{amount} · {sign}{Math.abs(change / base * 100).toFixed(1)}%
  </span>
}

/** One row of the results: what it is, then a value per code, compared codes
 * with their difference from the first. */
function ResultRow({ label, detail, items, value, cents = true, total = false }: {
  label: string; detail?: string; items: Calculation[]; value: (item: Calculation) => number
  cents?: boolean; total?: boolean
}) {
  const base = value(items[0])
  return <tr className={total ? 'pdpm-calc__total' : undefined}>
    <th scope="row">{label}{detail && <span className="pdpm-calc__detail">{detail}</span>}</th>
    {items.map((item, index) => <td key={item.code}>
      <span className="pdpm-calc__value">{cents ? money(value(item)) : wholeMoney(value(item))}</span>
      {index > 0 && <Difference value={value(item)} base={base} cents={cents} />}
    </td>)}
  </tr>
}

/** A run of days: its rate per day (a range when it spans several taper
 * steps), and what it earns, compared codes against the first. */
function PhaseRow({ label, detail, phases, items }: {
  label: string; detail: string; phases: (item: Calculation) => Phase[]; items: Calculation[]
}) {
  const revenue = (item: Calculation) => phases(item).reduce((sum, phase) => sum + phase.total, 0)
  const rate = (item: Calculation): ReactNode => {
    const runs = phases(item)
    const [first, last] = [runs[0], runs[runs.length - 1]]
    return first.rate === last.rate ? money(first.rate) : <>{money(first.rate)} → {money(last.rate)}</>
  }
  return <tr>
    <th scope="row">{label}<span className="pdpm-calc__detail">{detail}</span></th>
    {items.map((item, index) => <td key={item.code}>
      <span className="pdpm-calc__value">{rate(item)}</span>
      <span className="pdpm-calc__secondary">{wholeMoney(revenue(item))} earned</span>
      {index > 0 && <Difference value={revenue(item)} base={revenue(items[0])} />}
    </td>)}
  </tr>
}

type ScheduleRow = { phase: Phase; row: number }

/** The rate schedule's columns: the days and what they are, then each code's
 * rate and what the run earns, and for each compared code its difference from
 * the baseline as the shared table shows a change. */
function scheduleColumns(items: Calculation[], colorOf: (code: string) => string): TableColumn<ScheduleRow>[] {
  const [base] = items
  const earned = (item: Calculation, row: ScheduleRow) => item.phases[row.row].total
  return [
    { id: 'days', header: 'Days', isRowHeader: true, sortable: false, value: row => row.phase.start,
      format: (_, row) => `${row.phase.start}–${row.phase.end}` },
    { id: 'phase', header: 'Phase', sortable: false, value: row => row.phase.start === 1 ? 'NTA paid at 3×'
      : row.phase.label === 'Baseline' ? 'Full therapy rate' : `PT and OT less ${row.phase.label.replace(/\D/g, '')}%` },
    ...items.flatMap((item, index): TableColumn<ScheduleRow>[] => [
      { id: `${item.code}-rate`, header: `${item.code} / day`, marker: colorOf(item.code), numeric: true,
        sortable: false, value: row => item.phases[row.row].rate, format: value => money(Number(value)) },
      { id: `${item.code}-earned`, header: `${item.code} earned`, numeric: true, sortable: false,
        value: row => earned(item, row), format: value => wholeMoney(Number(value)) },
      ...(index === 0 ? [] : [{ id: `${item.code}-change`, header: `${item.code} vs ${base.code}`, numeric: true,
        sortable: false, value: (row: ScheduleRow) => earned(item, row) - earned(base, row),
        format: (value: unknown) => `${Number(value) > 0 ? '+' : Number(value) < 0 ? '−' : ''}${
          wholeMoney(Math.abs(Number(value)))}`,
        change: { favorable: 'increase' as const } }]),
    ]),
  ]
}

/** PDPM Calculator: a facility and up to three PDPM codes in, what each pays
 * over a full 100-day Medicare stay out, side by side, the first code the
 * baseline the others are measured against. Facility and codes are kept in
 * the URL. */
export function PdpmCalculator() {
  const [params, setParams] = useReportSearchParams()
  const [facilities, setFacilities] = useState<CalculatorFacility[] | null>(null)
  const [facilitiesError, setFacilitiesError] = useState<string | null>(null)
  const [facilitiesRetry, setFacilitiesRetry] = useState(0)
  const facilityId = params.get('calc_facility') ?? facilities?.[0]?.facility_id ?? null
  const facility = facilities?.find(item => item.facility_id === facilityId)
  const saved = params.getAll('code').map(code => code.toUpperCase())
  const codes = saved.length ? saved : [EXAMPLE_CODE]
  // What is typed in each box, kept apart from the URL so a half-typed code
  // never prices; the URL holds the whole, valid ones.
  const [typed, setTyped] = useState<string[]>(codes)
  const [results, setResults] = useState<{ key: string; items: Calculation[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  // The rate schedule modal: every run of days at one rate.
  const [schedule, setSchedule] = useState(false)
  const id = useId()
  const requestKey = `${facilityId}|${codes.join(',')}`

  useEffect(() => {
    const controller = new AbortController()
    void getCalculatorFacilities(controller.signal)
      .then(body => { if (!controller.signal.aborted) setFacilities(body.items) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setFacilitiesError(failure.message) })
    return () => controller.abort()
  }, [facilitiesRetry])

  useEffect(() => {
    if (!facilityId) return
    const controller = new AbortController()
    setError(null)
    // Each code is priced alone, in a few milliseconds; together they are one result.
    void Promise.all(codes.map(code => getPdpmCalculation(facilityId, code, controller.signal)))
      .then(items => { if (!controller.signal.aborted) setResults({ key: requestKey, items }) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
    // requestKey names the facility and every code.
  }, [requestKey, retry])

  const write = (update: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params)
    update(next)
    setParams(next)
  }
  // The URL follows the boxes once every filled box holds a whole, valid code:
  // each once, in order. While one is mid-edit the last complete set stays,
  // so a comparison never collapses under the cursor.
  const setCodes = (boxes: string[]) => {
    setTyped(boxes)
    if (boxes.some(box => problem(box))) return
    const valid = [...new Set(boxes.filter(box => CODE.test(box)))]
    if (valid.length && valid.join(',') !== codes.join(',')) write(next => {
      next.delete('code')
      valid.forEach(code => next.append('code', code))
    })
  }
  const onType = (index: number, value: string) =>
    setCodes(typed.map((box, at) => at === index ? value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5) : box))
  const problems = typed.map(problem)
  // A box mid-edit: the results still show the last whole codes, and say so.
  const unfinished = problems.some(Boolean)

  const items = results?.items ?? []
  const refreshing = results !== null && results.key !== requestKey && !error
  const colorOf = (code: string) => CODE_COLORS[Math.max(0, typed.indexOf(code)) % MAX_CODES]
  const phasesOf = (kind: 'nta' | 'baseline' | 'taper') => (item: Calculation) => item.phases.filter(phase =>
    kind === 'nta' ? phase.start === 1 : kind === 'baseline' ? phase.label === 'Baseline'
      : phase.start > 1 && phase.label !== 'Baseline')
  const [base] = items
  const taper = base ? phasesOf('taper')(base) : []
  const lastTaper = taper[taper.length - 1]

  // The card grows with the codes compared: a column each beside the labels.
  return <section className={`pdpm-calc pdpm-calc--codes-${Math.max(1, items.length)}`} aria-labelledby={`${id}-title`}>
    {/* The page has no report header (see App.tsx), so the card names itself. */}
    <header className="pdpm-calc__header">
      <h1 id={`${id}-title`}>PDPM Calculator</h1>
      <p>What a Medicare PDPM code pays over a full 100-day stay at one facility.</p>
    </header>
    <div className="pdpm-calc__inputs">
      <div className="pdpm-calc__facility">
        <FilterSelect label="Facility" value={facilityId}
          options={(facilities ?? []).map(item => ({ value: item.facility_id,
            label: `${item.facility_name} · ${item.state}` }))}
          loading={!facilities && !facilitiesError} error={facilitiesError}
          onRetry={() => { setFacilitiesError(null); setFacilitiesRetry(count => count + 1) }}
          onChange={value => write(next => next.set('calc_facility', value))} />
        <p className="pdpm-calc__help">{facility ? <>Base rate <strong>{money(facility.base_rate)}</strong> a day,
          its Original Medicare PDPM contract, in place of the $720 national rate.</> : ' '}</p>
      </div>

      <fieldset className="pdpm-calc__codes" aria-describedby={`${id}-key`}>
        <legend className="filter-dropdown__label">Care codes</legend>
        <div className="pdpm-calc__chips">
          {typed.map((box, index) => <div key={index}
            className={`pdpm-calc__chip${problems[index] ? ' pdpm-calc__chip--invalid' : ''}`}>
            <span className="pdpm-calc__swatch" style={{ background: CODE_COLORS[index] }} aria-hidden="true" />
            <label className="visually-hidden" htmlFor={`${id}-${index}`}>
              {index === 0 ? 'Baseline care code' : `Care code ${index + 1}, compared with the baseline`}</label>
            <input id={`${id}-${index}`} value={box} spellCheck={false} autoComplete="off" maxLength={5}
              placeholder={index === 0 ? EXAMPLE_CODE : 'Code'} aria-invalid={Boolean(problems[index])}
              aria-describedby={problems[index] ? `${id}-${index}-problem` : undefined}
              onChange={event => onType(index, event.target.value)} />
            {index > 0 && <button type="button" className="pdpm-calc__remove"
              aria-label={`Remove ${box || 'this code'}`} title="Remove"
              onClick={() => setCodes(typed.filter((_, at) => at !== index))}>
              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>}
          </div>)}
          <button type="button" className="pdpm-calc__add" disabled={typed.length >= MAX_CODES}
            title={typed.length >= MAX_CODES ? `Up to ${MAX_CODES} codes` : 'Compare another code'}
            onClick={() => setTyped([...typed, ''])}>+ Compare</button>
        </div>
        <p id={`${id}-key`} className="pdpm-calc__help">
          {problems.map((message, index) => message && <span key={index} id={`${id}-${index}-problem`}
            className="pdpm-calc__problem">{typed[index]}: {message}. </span>)}
          {!unfinished && <>Letters, in order: {LETTERS.join(' · ')}. The first code is the baseline.</>}
        </p>
      </fieldset>
    </div>

    {!base || error ? <div className="pdpm-calc__state">
      <DataState loading={!error} error={error} onRetry={() => setRetry(count => count + 1)} label="PDPM calculation" />
    </div> : <div className={`pdpm-calc__results${refreshing ? ' pdpm-calc__results--refreshing' : ''}`}
      aria-busy={refreshing}>
      <p className="visually-hidden" role="status">{items.map(item =>
        `${item.code}: ${wholeMoney(item.total_revenue)} over ${item.benefit_days} days`).join('; ')}</p>
      {unfinished && <p className="pdpm-calc__stale">Showing the last complete codes until the code is finished.</p>}
      <table className="pdpm-calc__table">
        <colgroup><col className="pdpm-calc__label-column" />{items.map(item =>
          <col key={item.code} className="pdpm-calc__value-column" />)}</colgroup>
        <thead>
          <tr>
            <th scope="col"><span className="visually-hidden">Measure</span></th>
            {items.map((item, index) => <th key={item.code} scope="col">
              <span className="pdpm-calc__code">
                <span className="pdpm-calc__swatch" style={{ background: colorOf(item.code) }} aria-hidden="true" />
                <span className="care-code">{item.code}</span>
              </span>
              {items.length > 1 && <span className="pdpm-calc__role">{index === 0 ? 'Baseline' : `vs ${base.code}`}</span>}
            </th>)}
          </tr>
        </thead>
        <tbody>
          <ResultRow total label={`${base.benefit_days}-day total`} detail="A full Medicare stay"
            items={items} value={item => item.total_revenue} cents={false} />
          <ResultRow label="Average per day" items={items} value={item => item.average_rate} />
          <ResultRow label="Day 1 rate" detail="NTA paid at 3×" items={items} value={item => item.day_one_rate} />
          <ResultRow label={`Day ${base.benefit_days} rate`}
            detail={`PT and OT at ${Math.round(base.last_therapy_factor * 100)}%`}
            items={items} value={item => item.last_day_rate} />
          <ResultRow label="NTA premium" detail="Extra from 3× NTA, days 1–3" items={items}
            value={item => item.nta_premium} />
        </tbody>
        <tbody className="pdpm-calc__phases">
          <tr className="pdpm-calc__section">
            <th scope="colgroup" colSpan={items.length + 1}>
              <div className="pdpm-calc__section-bar">
              <span>Rate by phase of the stay</span>
              <OpenViewButton kind="table" label="See full rate schedule" onClick={() => setSchedule(true)} />
              </div>
            </th>
          </tr>
          <PhaseRow label="Days 1–3" detail="NTA paid at 3×" phases={phasesOf('nta')} items={items} />
          <PhaseRow label="Days 4–20" detail="Full therapy rate" phases={phasesOf('baseline')} items={items} />
          {lastTaper && <PhaseRow label={`Days ${taper[0].start}–${lastTaper.end}`}
            detail={`PT and OT less 2% a week, to ${lastTaper.label.replace(/\D/g, '')}%`}
            phases={phasesOf('taper')} items={items} />}
        </tbody>
      </table>
      {/* Every run of days at one rate -- days 1-3, 4-20, then each taper step: the report
          detail modal and shared table every other report uses. */}
      <FullScreenModal open={schedule} onClose={() => setSchedule(false)} destroyOnHidden
        title={`Rate schedule: ${items.map(item => item.code).join(', ')} at ${base.facility.facility_name}`}>
        <div className="net-change-daily-modal__table">
          <Table<ScheduleRow> title="Rate schedule over the stay"
            subtitle={`Each run of days at one rate over the ${base.benefit_days}-day stay: NTA paid at 3× on days `
              + '1–3, the full therapy rate to day 20, then PT and OT 2% lower each week. Earned is the rate times '
              + `the run's days${items.length > 1 ? `; each comparison is against ${base.code}` : ''}.`}
            columns={scheduleColumns(items, colorOf)} rows={base.phases.map((phase, row) => ({ phase, row }))}
            getRowKey={row => String(row.phase.start)} emptyMessage="No days to show."
            csvFileName={`pdpm-calculator-rate-schedule-${items.map(item => item.code).join('-')}.csv`} />
        </div>
      </FullScreenModal>
    </div>}
  </section>
}

