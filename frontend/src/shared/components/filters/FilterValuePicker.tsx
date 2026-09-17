import { useId, useState, type ReactNode } from 'react'
import type { MultiSelectFilterOption } from './MultiSelectFilterOptions'

export type FilterPickerOption = MultiSelectFilterOption & { context?: string }
type FilterValuePickerProps = {
  label: string
  options: FilterPickerOption[]
  availableOptions?: FilterPickerOption[]
  values: string[]
  onChange: (values: string[]) => void
  singleSelect?: boolean
  renderListControls?: () => ReactNode
}

export function FilterValuePicker({ label, options, availableOptions = options, values, onChange,
  singleSelect = false, renderListControls }: FilterValuePickerProps) {
  const id = useId()
  const [query, setQuery] = useState('')
  const search = query.trim().toLowerCase()
  const matches = availableOptions.filter((option) =>
    `${option.label} ${option.context ?? ''}`.toLowerCase().includes(search))

  return <div className="filter-value-picker">
    {renderListControls?.()}
    <label className="filter-value-picker__search" htmlFor={id}>
      <span>Search {label.toLowerCase()}</span>
      <input id={id} type="search" value={query}
        placeholder="Search by name"
        onChange={(event) => setQuery(event.target.value)} />
    </label>
    <p className="filter-value-picker__counts" role="status" aria-live="polite" aria-atomic="true">
      Showing {matches.length.toLocaleString()} of {options.length.toLocaleString()} {label.toLowerCase()}
      {values.length === 0 ? ` - All ${label.toLowerCase()} included` : ` - ${values.length.toLocaleString()} selected`}
    </p>
    <div className="location-filter__selection-bar">
      <button type="button" className="filter-value-picker__select-all" disabled={singleSelect}
        onClick={() => onChange(options.map((option) => option.value))}>
        Select all
      </button>
      <button type="button" className="filter-value-picker__unselect-all"
        onClick={() => onChange([])}>Unselect all</button>
    </div>
    <hr className="filter-value-picker__divider" />
    <div className="filter-value-picker__list" role="group" aria-label={`${label} options`}>
      {matches.map((option) => <label className="filter-value-picker__option" key={option.value}>
        <input checked={values.includes(option.value)} type={singleSelect ? 'radio' : 'checkbox'}
          name={singleSelect ? id : undefined} onChange={() => onChange(values.includes(option.value)
            ? values.filter((value) => value !== option.value) : singleSelect ? [option.value] : [...values, option.value])} />
        <span>{option.label}{option.context && <small className="filter-value-picker__context">{option.context}</small>}</span>
      </label>)}
      {matches.length === 0 && <p className="filter-value-picker__empty" role="status">
        No options match. Change your search.
      </p>}
    </div>
  </div>
}
