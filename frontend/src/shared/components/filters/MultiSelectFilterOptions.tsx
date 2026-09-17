import { useMemo, useState } from 'react'

export type MultiSelectFilterOption = {
  label: string
  value: string
}

type MultiSelectFilterOptionsProps = {
  autoFocus?: boolean
  label: string
  onChange: (values: string[]) => void
  options: MultiSelectFilterOption[]
  selectedValues: string[]
  showSearchLabel?: boolean
}

export function MultiSelectFilterOptions({
  autoFocus = true,
  label,
  onChange,
  options,
  selectedValues,
  showSearchLabel = false,
}: MultiSelectFilterOptionsProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const visibleOptions = useMemo(
    () => options.filter((option) => option.label.toLowerCase().includes(searchTerm.toLowerCase())),
    [options, searchTerm],
  )

  return (
    <>
      <label className="multi-select-filter__search">
        <span className={showSearchLabel ? undefined : 'visually-hidden'}>Search {label}</span>
        <input
          autoFocus={autoFocus}
          onChange={(event) => setSearchTerm(event.target.value)}
          placeholder={`Search ${label}`}
          type="search"
          value={searchTerm}
        />
      </label>
      <div className="multi-select-filter__actions">
        <button
          disabled={visibleOptions.length === 0}
          onClick={() => {
            const visibleValues = visibleOptions.map((option) => option.value)
            onChange(searchTerm ? [...new Set([...selectedValues, ...visibleValues])] : visibleValues)
          }}
          type="button"
        >
          {searchTerm ? 'Select matches' : 'Select all'}
        </button>
        <button className="multi-select-filter__clear" onClick={() => onChange([])} type="button">
          Clear
        </button>
      </div>
      <div className="multi-select-filter__list">
        {visibleOptions.length === 0 ? (
          <p className="multi-select-filter__empty">No matching options.</p>
        ) : (
          visibleOptions.map((option) => (
            <label className="multi-select-filter__option" key={option.value}>
              <input
                checked={selectedValues.includes(option.value)}
                onChange={() =>
                  onChange(
                    selectedValues.includes(option.value)
                      ? selectedValues.filter((selectedOption) => selectedOption !== option.value)
                      : [...selectedValues, option.value],
                  )
                }
                type="checkbox"
              />
              <span>{option.label}</span>
            </label>
          ))
        )}
      </div>
    </>
  )
}
