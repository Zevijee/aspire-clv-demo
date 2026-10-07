import { useId, useMemo, useState } from 'react'
import { Button, Modal } from 'antd'
import { FilterValuePicker } from './filters/FilterValuePicker'
import { useAdmissionsReferences } from '../../features/adt/hooks/useAdmissionsOverview'
import {
  levelLabels, locationLevels, locationOptions, useCustomGrouping, type LocationLevel,
} from '../customGrouping'

/** Opens the custom grouping picker: a level, then the locations at it. The
 * grouping is app-wide, so applying it here changes every drilldown. */
export function CustomGroupingButton({ onApply }: { onApply?: () => void }) {
  const { grouping } = useCustomGrouping()
  const [open, setOpen] = useState(false)
  return <>
    <button type="button" className="report-table__view-action custom-grouping__button"
      aria-pressed={Boolean(grouping)} onClick={() => setOpen(true)}>
      <svg aria-hidden="true" className="report-table__view-action-icon" fill="none" viewBox="0 0 24 24">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <path d="M17.5 14v7M14 17.5h7" />
      </svg>
      Custom grouping
    </button>
    {open && <CustomGroupingModal onClose={() => setOpen(false)} onApply={onApply} />}
  </>
}

function CustomGroupingModal({ onClose, onApply }: { onClose: () => void; onApply?: () => void }) {
  const id = useId()
  const { grouping, setGrouping } = useCustomGrouping()
  const references = useAdmissionsReferences()
  const [level, setLevel] = useState<LocationLevel>(grouping?.level ?? 'region')
  // Each level keeps its own picks while the reader switches between them.
  const [picks, setPicks] = useState<Partial<Record<LocationLevel, string[]>>>(
    grouping ? { [grouping.level]: grouping.locations } : {})
  const values = picks[level] ?? []
  const locations = references.data?.locations
  const options = useMemo(() => locationOptions(locations ?? [], level), [locations, level])
  const apply = (next: typeof grouping) => { setGrouping(next); onApply?.(); onClose() }

  return <Modal open centered onCancel={onClose} title="Custom grouping" width={560}
    footer={[
      grouping && <Button key="clear" danger onClick={() => apply(null)}>Clear grouping</Button>,
      <Button key="cancel" onClick={onClose}>Cancel</Button>,
      <Button key="apply" type="primary" disabled={!values.length}
        onClick={() => apply({ level, locations: values })}>Apply</Button>,
    ]}>
    <div className="location-filter custom-grouping__picker">
      <p className="custom-grouping__hint">Choose what to group by, then the ones to show. Every drilldown
        starts from them until the grouping is cleared.</p>
      <fieldset className="location-filter__level-control">
        <legend>Group by</legend>
        <div className="location-filter__levels">
          {locationLevels.map(item => <label className="location-filter__level" key={item}>
            <input className="visually-hidden" type="radio" name={`${id}-level`} value={item}
              checked={level === item} onChange={() => setLevel(item)} />
            <span>{levelLabels[item].one}</span>
          </label>)}
        </div>
      </fieldset>
      {references.error
        ? <p role="alert">{references.error} <Button size="small" onClick={references.onRetry}>Retry</Button></p>
        : references.loading ? <p className="custom-grouping__hint">Loading locations…</p>
        : <FilterValuePicker key={level} label={levelLabels[level].many} options={options} values={values}
            onChange={next => setPicks(current => ({ ...current, [level]: next }))} />}
    </div>
  </Modal>
}
