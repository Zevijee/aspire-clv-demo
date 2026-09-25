import { useEffect, useState } from 'react'
import { DataState } from '../../../shared/components/DataState'
import { FilterSelect } from '../../../shared/components/filters/FilterSelect'
import { useReportSearchParams } from '../../../shared/components/ReportSearchContext'
import { payerLabels } from '../../adt/api/admissionsOverview'
import { ResidentModal, type ResidentIdentity } from './ResidentModal'
import {
  getBedBoard, getBedBoardFacilities,
  type BedBoardFacility, type BedBoardReport, type BedOccupant,
} from '../api'

const PARAM = 'bed_facility'
type Bed = BedBoardReport['beds'][number]
type Room = { room: string; beds: Bed[] }
type Wing = { wing: string; rooms: Room[] }

const careLevelTags: Record<string, string> = { Low: 'LOW', Moderate: 'MOD', High: 'HIGH', Complex: 'CPLX' }
const shortDate = (value: string) => new Date(`${value}T00:00:00`)
  .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
const daysBetween = (from: string, to: string) =>
  Math.round((new Date(`${to}T00:00:00`).getTime() - new Date(`${from}T00:00:00`).getTime()) / 86_400_000)
const money = (value: number) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD' })

/** Skilled residents show SKL and hospice HOS; everyone else their care level. */
function tag(occupant: BedOccupant) {
  if (occupant.is_skilled) return 'SKL'
  if (occupant.payer_type === 'hospice') return 'HOS'
  return careLevelTags[occupant.care_level] ?? occupant.care_level
}

function group(beds: Bed[]) {
  const wings: Wing[] = []
  for (const bed of beds) {
    let wing = wings.at(-1)
    if (wing?.wing !== bed.wing) wings.push(wing = { wing: bed.wing, rooms: [] })
    let room = wing.rooms.at(-1)
    if (room?.room !== bed.room) wing.rooms.push(room = { room: bed.room, beds: [] })
    room.beds.push(bed)
  }
  return wings
}

/** The facility picker for the report header. The board shows one facility at
 * a time; with none chosen, the API's default -- the first by name -- is shown. */
export function BedBoardFacilityFilter() {
  const [params, setParams] = useReportSearchParams()
  const [retry, setRetry] = useState(0)
  const [facilities, setFacilities] = useState<BedBoardFacility[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getBedBoardFacilities(controller.signal)
      .then(data => { if (!controller.signal.aborted) { setFacilities(data); setError(null) } })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [retry])

  return <FilterSelect label="Facility" value={params.get(PARAM) ?? facilities?.[0]?.facility_id ?? null}
    options={(facilities ?? []).map(facility => ({
      value: facility.facility_id, label: `${facility.facility_name} · ${facility.state}` }))}
    loading={!facilities && !error} error={error} onRetry={() => { setError(null); setRetry(value => value + 1) }}
    onChange={value => {
      const next = new URLSearchParams(params)
      next.set(PARAM, value)
      setParams(next)
    }} />
}

function BedCard({ bed, censusDate, onOpen }: { bed: Bed; censusDate: string; onOpen: (occupant: BedOccupant) => void }) {
  const occupant = bed.occupant
  if (!occupant) return <div className="bed-card bed-card--open" aria-label={`Bed ${bed.room}${bed.bed}, open`}>
    <span className="bed-card__bed">{bed.bed}</span>
    <strong>OPEN</strong>
  </div>
  const gender = occupant.gender === 'male' ? 'M' : 'F'
  const name = `${occupant.last_name}, ${occupant.first_name.charAt(0)}.`
  const payer = payerLabels[occupant.payer_type] ?? occupant.payer_type
  const hover = [
    `${occupant.first_name} ${occupant.last_name}`,
    `${occupant.payer_name} (${payer})`,
    occupant.skilled_day !== null ? `Skilled day ${occupant.skilled_day}` : `Care level: ${occupant.care_level}`,
    `Admitted ${shortDate(occupant.admission_date)} · ${daysBetween(occupant.admission_date, censusDate)} days`,
    `Daily rate ${money(occupant.daily_rate)}`,
  ].join('\n')
  return <button type="button" className={`bed-card bed-card--${occupant.gender}`} title={hover}
    aria-label={`Bed ${bed.room}${bed.bed}: ${occupant.first_name} ${occupant.last_name}, ${payer}`}
    onClick={() => onOpen(occupant)}>
    <span className="bed-card__bed">{bed.bed}</span>
    <span className="bed-card__who">
      <strong>{name}</strong>
      <span>{payer}</span>
    </span>
    <span className="bed-card__marks">
      <span className="bed-card__gender" aria-hidden="true">{gender}</span>
      <span className="bed-card__tag">{tag(occupant)}</span>
    </span>
  </button>
}

/** One facility's beds on the latest census day, wing by wing and room by room. */
export function BedBoard() {
  const [params] = useReportSearchParams()
  const facilityId = params.get(PARAM)
  const requestKey = facilityId ?? ''
  const [retry, setRetry] = useState(0)
  const [response, setResponse] = useState<{ key: string; data: BedBoardReport } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [opened, setOpened] = useState<ResidentIdentity | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getBedBoard(requestKey || null, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResponse({ key: requestKey, data }) })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [requestKey, retry])

  const data = response?.key === requestKey ? response.data : null
  const error = failure?.key === requestKey ? failure.message : null
  if (!data) return <section className="bed-board" aria-label="Bed board">
    <DataState loading={!error} error={error} label="bed board" onRetry={() => { setFailure(null); setRetry(value => value + 1) }} />
  </section>

  const occupied = data.beds.filter(bed => bed.occupant).length
  const total = data.beds.length
  const open = (occupant: BedOccupant) => setOpened({
    resident_name: `${occupant.first_name} ${occupant.last_name}`,
    facility_name: data.facility_name, region: data.region, state: data.state })

  return <section className="bed-board" aria-label={`Bed board for ${data.facility_name}`}>
    <div className="bed-board__summary">
      <dl className="bed-board__totals">
        <div><dt>beds</dt><dd>{total}</dd></div>
        <div><dt>occupied</dt><dd>{occupied}</dd></div>
        <div className="bed-board__total--open"><dt>open</dt><dd>{total - occupied}</dd></div>
        <div><dt>occupancy</dt><dd>{total ? Math.round(occupied / total * 100) : 0}%</dd></div>
      </dl>
      <span className="bed-board__as-of">As of {shortDate(data.census_date)}</span>
      <ul className="bed-board__legend" aria-label="Legend">
        <li><span className="bed-board__swatch bed-board__swatch--male" />Male</li>
        <li><span className="bed-board__swatch bed-board__swatch--female" />Female</li>
        <li><span className="bed-board__swatch bed-board__swatch--open" />Open</li>
      </ul>
    </div>

    {data.waiting.length > 0 && <p className="bed-board__waiting" role="status">
      Waiting for a bed: {data.waiting.map(occupant => `${occupant.last_name}, ${occupant.first_name.charAt(0)}.`).join('; ')}
    </p>}

    {group(data.beds).map(wing => {
      const beds = wing.rooms.flatMap(room => room.beds)
      const full = beds.filter(bed => bed.occupant).length
      return <section className="bed-board__wing" key={wing.wing} aria-label={`Wing ${wing.wing}`}>
        <header className="bed-board__wing-header">
          <h2>Wing {wing.wing}</h2>
          <span>
            {wing.rooms.length} rooms / {beds.length} beds / {full} occupied /
            <span className="bed-board__open-count">{beds.length - full} open</span>
          </span>
        </header>
        <div className="bed-board__rooms">
          {wing.rooms.map(room => {
            const taken = room.beds.filter(bed => bed.occupant).length
            return <div className="bed-board__room" key={room.room}>
              <div className="bed-board__room-number">
                <strong>{room.room}</strong>
                <span>{taken}/{room.beds.length} full</span>
              </div>
              {room.beds.map(bed => <BedCard key={bed.bed} bed={bed} censusDate={data.census_date} onOpen={open} />)}
            </div>
          })}
        </div>
      </section>
    })}
    <ResidentModal resident={opened} onClose={() => setOpened(null)} />
  </section>
}
