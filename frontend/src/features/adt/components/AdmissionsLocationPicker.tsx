import { useId, useMemo, useRef } from 'react'
import type { AdmissionsFilterOptions } from '../api/admissions'
import { FilterValuePicker } from '../../../shared/components/filters/FilterValuePicker'
import { getLocationOptions, getLocationLevel, type LocationLevel } from '../utils/admissionsOverviewFilters'

const levels: { value: LocationLevel; label: string; plural: string }[] = [
  { value: 'state', label: 'State', plural: 'States' },
  { value: 'portfolio', label: 'Portfolio', plural: 'Portfolios' },
  { value: 'region', label: 'Region', plural: 'Regions' },
  { value: 'facility', label: 'Facility', plural: 'Facilities' },
]

export function AdmissionsLocationPicker({ locations, values, onChange, settings, onSettingsChange }: {
  locations: AdmissionsFilterOptions['locations']
  values: string[]
  onChange: (values: string[]) => void
  settings: Record<string, string[]>
  onSettingsChange: (settings: Record<string, string[]>) => void
}) {
  const id = useId()
  const level = (settings.level?.[0] ?? getLocationLevel(values) ?? 'state') as LocationLevel
  const savedValues = useRef<Partial<Record<LocationLevel, string[]>>>({})
  const options = useMemo(() => getLocationOptions(locations, level), [locations, level])
  const scope = settings.scope?.[0] ? JSON.parse(settings.scope[0]) as Record<string, string> : null

  return <div className="location-filter">
    <fieldset className="location-filter__level-control">
      <legend>Break down by</legend>
      <div className="location-filter__levels">
        {levels.map((item) => <label className="location-filter__level" key={item.value}>
          <input className="visually-hidden" type="radio" name={`${id}-level`}
            value={item.value} checked={level === item.value} onChange={() => {
              savedValues.current[level] = [...values]
              onChange(savedValues.current[item.value] ?? [])
              onSettingsChange({ level: [item.value], scope: [] })
            }} />
          <span>{item.label}</span>
        </label>)}
      </div>
    </fieldset>
    {scope && <div className="location-filter__scope" role="status">
      <span><strong>Current drill-down:</strong> {Object.values(scope).filter(Boolean).join(' / ')}</span>
      <button type="button" className="location-filter__reset-narrowing"
        onClick={() => onSettingsChange({ scope: [] })}>Return to full selection</button>
    </div>}
    <FilterValuePicker key={level} label={levels.find((item) => item.value === level)!.plural}
      options={options} values={values} onChange={(next) => { onChange(next); onSettingsChange({ scope: [] }) }}
      />
  </div>
}
