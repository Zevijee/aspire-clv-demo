import { useId, useMemo, useRef, useState } from 'react'
import { Popover } from 'antd'
import { DataState, type DataStateProps } from '../DataState'

export type FilterSelectOption = { label: string; value: string }

/** The single-choice sibling of `FilterDropdown`: the same trigger and panel,
 * with a search box and a list where picking an option closes the panel. For
 * reports that show exactly one of something, such as one facility. */
export function FilterSelect({ label, options, value, onChange, loading, error, onRetry }: DataStateProps & {
  label: string
  options: FilterSelectOption[]
  value: string | null
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const visible = useMemo(() => options.filter(option =>
    option.label.toLowerCase().includes(search.toLowerCase())), [options, search])
  const summary = options.find(option => option.value === value)?.label ?? (loading ? 'Loading…' : `Choose ${label.toLowerCase()}`)
  const close = () => { setOpen(false); setSearch(''); trigger.current?.focus() }

  return <div className="filter-dropdown filter-select">
    <label className="filter-dropdown__label" htmlFor={`${id}-trigger`}>{label}</label>
    <Popover open={open} onOpenChange={next => { setOpen(next); if (!next) setSearch('') }} trigger="click"
      placement="bottomLeft" destroyOnHidden content={<div id={id} role="dialog" aria-label={`Choose ${label.toLowerCase()}`}
        className="filter-dropdown__panel filter-select__panel" onKeyDown={event => {
          if (event.key === 'Escape') { event.stopPropagation(); close() }
        }}>
        {loading || error ? <DataState loading={loading} error={error} onRetry={onRetry} label={label} /> : <>
          <label className="multi-select-filter__search">
            <span className="visually-hidden">Search {label}</span>
            <input autoFocus type="search" placeholder={`Search ${label}`} value={search}
              onChange={event => setSearch(event.target.value)} onKeyDown={event => {
                if (event.key === 'Enter' && visible.length > 0) { onChange(visible[0].value); close() }
              }} />
          </label>
          <div className="multi-select-filter__list" role="listbox" aria-label={label}>
            {visible.length === 0 ? <p className="multi-select-filter__empty">No matching options.</p>
              : visible.map(option => <button key={option.value} type="button" role="option"
                aria-selected={option.value === value}
                className={`filter-select__option${option.value === value ? ' filter-select__option--selected' : ''}`}
                onClick={() => { onChange(option.value); close() }}>{option.label}</button>)}
          </div>
        </>}
      </div>}>
      <button id={`${id}-trigger`} ref={trigger} type="button" className="filter-dropdown__trigger"
        aria-label={`${label}: ${summary}`} aria-haspopup="dialog" aria-expanded={open}
        aria-controls={open ? id : undefined}>
        <span>{summary}</span>
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
    </Popover>
  </div>
}
