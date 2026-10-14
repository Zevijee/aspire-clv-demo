import { useId, useState, type ReactNode } from 'react'
import type { MultiSelectFilterOption } from './MultiSelectFilterOptions'

export type FilterPickerOption = MultiSelectFilterOption & { context?: string }

/** Options by context, in the order each context first comes. */
function groups(options: FilterPickerOption[]) {
  const byContext = new Map<string, FilterPickerOption[]>()
  for (const option of options) {
    const context = option.context ?? ''
    byContext.set(context, [...(byContext.get(context) ?? []), option])
  }
  return [...byContext]
}
type FilterValuePickerProps = {
  label: string
  options: FilterPickerOption[]
  availableOptions?: FilterPickerOption[]
  values: string[]
  onChange: (values: string[]) => void
  singleSelect?: boolean
  renderListControls?: () => ReactNode
  /** List the options under a heading per `context`, in the order the contexts
   * first come, in place of each option's own context line: staffing roles
   * under their departments. In a multi-select each heading is a checkbox for
   * its options shown: ticking it selects them all, unticking clears them, and
   * it shows a partial tick when only some are selected. */
  groupByContext?: boolean
  /** In a dropdown: smaller Select all / Unselect all buttons above the
   * search, and the search label and counts line kept for screen readers only.
   * The side drawer shows them all in full. */
  compact?: boolean
}

export function FilterValuePicker({ label, options, availableOptions = options, values, onChange,
  singleSelect = false, renderListControls, groupByContext = false, compact = false }: FilterValuePickerProps) {
  const id = useId()
  const [query, setQuery] = useState('')
  const search = query.trim().toLowerCase()
  const matches = availableOptions.filter((option) =>
    `${option.label} ${option.context ?? ''}`.toLowerCase().includes(search))

  const renderOption = (option: FilterPickerOption, showContext: boolean) =>
    <label className="filter-value-picker__option" key={option.value}>
      <input checked={values.includes(option.value)} type={singleSelect ? 'radio' : 'checkbox'}
        name={singleSelect ? id : undefined} onChange={() => onChange(values.includes(option.value)
          ? values.filter((value) => value !== option.value) : singleSelect ? [option.value] : [...values, option.value])} />
      <span>{option.label}{showContext && option.context
        && <small className="filter-value-picker__context">{option.context}</small>}</span>
    </label>

  // A heading's checkbox: every option shown under it in, or all of them out.
  const renderGroupToggle = (context: string, members: FilterPickerOption[]) => {
    const codes = members.map(option => option.value)
    const chosen = codes.filter(code => values.includes(code)).length
    const all = chosen === codes.length
    return <label className="filter-value-picker__group-label filter-value-picker__group-toggle">
      <input type="checkbox" checked={all} aria-label={`All ${context}`}
        ref={input => { if (input) input.indeterminate = chosen > 0 && !all }}
        onChange={() => onChange(all ? values.filter(value => !codes.includes(value))
          : [...values, ...codes.filter(code => !values.includes(code))])} />
      {context}
    </label>
  }
  const searchBox = <label className="filter-value-picker__search" htmlFor={id}>
    {/* In a dropdown the placeholder says it; the label stays for screen readers. */}
    <span className={compact ? 'visually-hidden' : undefined}>Search {label.toLowerCase()}</span>
    <input id={id} type="search" value={query}
      placeholder="Search by name"
      onChange={(event) => setQuery(event.target.value)} />
  </label>
  const countsLine = <p className={`filter-value-picker__counts${compact ? ' visually-hidden' : ''}`} role="status"
    aria-live="polite" aria-atomic="true">
    Showing {matches.length.toLocaleString()} of {options.length.toLocaleString()} {label.toLowerCase()}
    {values.length === 0 ? ` - All ${label.toLowerCase()} included` : ` - ${values.length.toLocaleString()} selected`}
  </p>
  const selectionBar = <div className="location-filter__selection-bar">
    <button type="button" className="filter-value-picker__select-all" disabled={singleSelect}
      onClick={() => onChange(options.map((option) => option.value))}>
      Select all
    </button>
    <button type="button" className="filter-value-picker__unselect-all"
      onClick={() => onChange([])}>Unselect all</button>
  </div>

  return <div className={`filter-value-picker${compact ? ' filter-value-picker--compact' : ''}`}>
    {renderListControls?.()}
    {/* In a dropdown the buttons come first, the search right above the list. */}
    {compact ? <>{selectionBar}{searchBox}{countsLine}</> : <>{searchBox}{countsLine}{selectionBar}</>}
    <hr className="filter-value-picker__divider" />
    <div className="filter-value-picker__list" role="group" aria-label={`${label} options`}>
      {groupByContext ? groups(matches).map(([context, members]) =>
        <div className="filter-value-picker__group" role="group" aria-label={context} key={context}>
          {singleSelect ? <span className="filter-value-picker__group-label" aria-hidden="true">{context}</span>
            : renderGroupToggle(context, members)}
          {members.map(option => renderOption(option, false))}
        </div>) : matches.map(option => renderOption(option, true))}
      {matches.length === 0 && <p className="filter-value-picker__empty" role="status">
        No options match. Change your search.
      </p>}
    </div>
  </div>
}
