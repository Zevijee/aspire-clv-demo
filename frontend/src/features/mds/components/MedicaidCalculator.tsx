import { useEffect, useId, useState } from 'react'
import { DataState } from '../../../shared/components/DataState'
import { FilterSelect } from '../../../shared/components/filters/FilterSelect'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { getMedicaidCalculation, getMedicaidCalculatorFacilities, type CalculatorFacility, type MedicaidCalculation } from '../api'

const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
const wholeMoney = (value: number) => value.toLocaleString(undefined,
  { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
// A letter, a digit and a letter: nursing A-Y, cognitive impairment 0-3, NTA A-F.
const CODE = /^[A-Y][0-3][A-F]$/
const EXAMPLE_CODE = 'K2D'
// The baseline and up to two codes against it, each in its own colour.
const CODE_COLORS = ['var(--color-chart-series-primary)', 'var(--color-chart-series-tertiary)',
  'var(--color-chart-series-quinary)']
const MAX_CODES = CODE_COLORS.length
const PARTS = ['Nursing', 'Cognitive impairment', 'NTA']
const RANGES = ['A-Y', '0-3', 'A-F']

/** Why a box's code is not priced yet, or null when it is fine. */
function problem(box: string) {
  if (!box) return null
  if (box.length < 3) return 'Needs a letter, a digit and a letter'
  if (!CODE.test(box)) {
    const at = [...box].findIndex((character, index) => !new RegExp(`^[${RANGES[index]}]$`).test(character))
    return at >= 0 ? `${PARTS[at]} must be ${RANGES[at]}` : 'Not a Texas Medicaid code'
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
  label: string; detail?: string; items: MedicaidCalculation[]; value: (item: MedicaidCalculation) => number
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

/** Medicaid Calculator: a Texas facility and up to three Medicaid case-mix
 * codes in, what each pays a day and over a month out, by component, side by
 * side, the first code the baseline. The same rule prices the Medicaid
 * Worksheet's codes. Facility and codes are kept in the URL. */
export function MedicaidCalculator() {
  const [params, setParams] = useReportSearchParams()
  const [facilities, setFacilities] = useState<CalculatorFacility[] | null>(null)
  const [facilitiesError, setFacilitiesError] = useState<string | null>(null)
  const [facilitiesRetry, setFacilitiesRetry] = useState(0)
  const facilityId = params.get('calc_facility') ?? facilities?.[0]?.facility_id ?? null
  const facility = facilities?.find(item => item.facility_id === facilityId)
  const saved = params.getAll('code').map(code => code.toUpperCase())
  const codes = saved.length ? saved : [EXAMPLE_CODE]
  const [typed, setTyped] = useState<string[]>(codes)
  const [results, setResults] = useState<{ key: string; items: MedicaidCalculation[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const id = useId()
  const requestKey = `${facilityId}|${codes.join(',')}`

  useEffect(() => {
    const controller = new AbortController()
    void getMedicaidCalculatorFacilities(controller.signal)
      .then(body => { if (!controller.signal.aborted) setFacilities(body.items) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setFacilitiesError(failure.message) })
    return () => controller.abort()
  }, [facilitiesRetry])

  useEffect(() => {
    if (!facilityId) return
    const controller = new AbortController()
    setError(null)
    void Promise.all(codes.map(code => getMedicaidCalculation(facilityId, code, controller.signal)))
      .then(items => { if (!controller.signal.aborted) setResults({ key: requestKey, items }) })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
    // requestKey names the facility and every code.
  }, [requestKey, retry]) // eslint-disable-line react-hooks/exhaustive-deps

  const write = (update: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params)
    update(next)
    setParams(next)
  }
  // The URL follows the boxes once every filled box holds a whole, valid code.
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
    setCodes(typed.map((box, at) => at === index ? value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 3) : box))
  const problems = typed.map(problem)
  const unfinished = problems.some(Boolean)

  const items = results?.items ?? []
  const refreshing = results !== null && results.key !== requestKey && !error
  const colorOf = (code: string) => CODE_COLORS[Math.max(0, typed.indexOf(code)) % MAX_CODES]
  const [base] = items
  const componentOf = (item: MedicaidCalculation, key: string) => item.components.find(part => part.id === key)!

  return <section className={`pdpm-calc pdpm-calc--codes-${Math.max(1, items.length)}`} aria-labelledby={`${id}-title`}>
    {/* The page has no report header (see App.tsx), so the card names itself. */}
    <header className="pdpm-calc__header">
      <h1 id={`${id}-title`}>Medicaid Calculator</h1>
      <p>What a Texas Medicaid case-mix code pays at one facility, a day and over a {base?.stay_days ?? 30}-day month.</p>
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
          its State Medicaid rate: what the average resident pays.</> : ' '}</p>
      </div>

      <fieldset className="pdpm-calc__codes" aria-describedby={`${id}-key`}>
        <legend className="filter-dropdown__label">Care codes</legend>
        <div className="pdpm-calc__chips">
          {typed.map((box, index) => <div key={index}
            className={`pdpm-calc__chip${problems[index] ? ' pdpm-calc__chip--invalid' : ''}`}>
            <span className="pdpm-calc__swatch" style={{ background: CODE_COLORS[index] }} aria-hidden="true" />
            <label className="visually-hidden" htmlFor={`${id}-${index}`}>
              {index === 0 ? 'Baseline care code' : `Care code ${index + 1}, compared with the baseline`}</label>
            <input id={`${id}-${index}`} value={box} spellCheck={false} autoComplete="off" maxLength={3}
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
          {!unfinished && <>In order: {PARTS.map((part, index) => `${part} ${RANGES[index]}`).join(' · ')}. The first code is the baseline.</>}
        </p>
      </fieldset>
    </div>

    {!base || error ? <div className="pdpm-calc__state">
      <DataState loading={!error} error={error} onRetry={() => setRetry(count => count + 1)} label="Medicaid calculation" />
    </div> : <div className={`pdpm-calc__results${refreshing ? ' pdpm-calc__results--refreshing' : ''}`}
      aria-busy={refreshing}>
      <p className="visually-hidden" role="status">{items.map(item =>
        `${item.code}: ${money(item.daily_rate)} a day, ${wholeMoney(item.total_revenue)} over ${item.stay_days} days`).join('; ')}</p>
      {unfinished && <p className="pdpm-calc__stale">Showing the last complete codes until the code is finished.</p>}
      <table className="pdpm-calc__table">
        <colgroup><col className="pdpm-calc__label-column" />{items.map(item =>
          <col key={item.code} className="pdpm-calc__value-column" />)}</colgroup>
        <thead>
          <tr>
            <th scope="col"><span className="visually-hidden">Measure</span></th>
            {items.map(item => <th key={item.code} scope="col">
              <span className="pdpm-calc__code">
                <span className="pdpm-calc__swatch" style={{ background: colorOf(item.code) }} aria-hidden="true" />
                <span className="care-code">{item.code}</span>
              </span>
              <span className="pdpm-calc__detail">{item.cognitive_level} cognition</span>
            </th>)}
          </tr>
        </thead>
        <tbody>
          <ResultRow label="Nursing" detail={`${money(componentOf(base, 'nursing').base)} share × CMI against the average`}
            items={items} value={item => componentOf(item, 'nursing').adjusted} />
          <ResultRow label="Cognitive impairment" detail="add-on, 0 to 10% of the base"
            items={items} value={item => componentOf(item, 'cognitive').adjusted} />
          <ResultRow label="NTA" detail={`${money(componentOf(base, 'nta').base)} share × CMI against the average`}
            items={items} value={item => componentOf(item, 'nta').adjusted} />
          <ResultRow label="Non-case-mix" detail="the same for every code"
            items={items} value={item => componentOf(item, 'non_case_mix').adjusted} />
          <ResultRow label="Daily rate" detail={`neutral ${money(base.neutral_rate)}`} items={items}
            value={item => item.daily_rate} total />
          <ResultRow label={`${base.stay_days}-day revenue`} items={items} value={item => item.total_revenue}
            cents={false} total />
        </tbody>
      </table>
    </div>}
  </section>
}
