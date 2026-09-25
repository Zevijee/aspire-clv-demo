import { useId, useRef, useState } from 'react'
import { Popover } from 'antd'
import { FilterValuePicker, type FilterPickerOption } from './FilterValuePicker'
import { MultiSelectFilterOptions } from './MultiSelectFilterOptions'
import { DataState, type DataStateProps } from '../DataState'

type FilterDropdownProps = DataStateProps & {
  label: string
  options: FilterPickerOption[]
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
  variant?: 'compact' | 'detailed'
  /** Told when the list opens or closes, for options that load on demand. */
  onOpenChange?: (open: boolean) => void
}

export function FilterDropdown({ label, options, values, onChange,
  placeholder = `All ${label.toLowerCase()}`, variant = 'compact', loading, error, onRetry,
  onOpenChange }: FilterDropdownProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const summary = values.length === 0 ? placeholder : `${values.length} selected`

  return <div className="filter-dropdown">
    <label className="filter-dropdown__label" htmlFor={`${id}-trigger`}>{label}</label>
    <Popover open={open} onOpenChange={next => { setOpen(next); onOpenChange?.(next) }} trigger="click" placement="bottomLeft"
    destroyOnHidden content={<div id={id} role="dialog" aria-label={`Filter ${label.toLowerCase()}`}
      className="filter-dropdown__panel" onKeyDown={event => {
        if (event.key === 'Escape') {
          event.stopPropagation()
          setOpen(false)
          onOpenChange?.(false)
          trigger.current?.focus()
        }
      }}>
      {loading || error ? <DataState loading={loading} error={error} onRetry={onRetry} label={label} /> : variant === 'detailed'
        ? <FilterValuePicker label={label} options={options} values={values} onChange={onChange} />
        : <MultiSelectFilterOptions label={label} options={options} selectedValues={values} onChange={onChange} />}
    </div>}>
    <button id={`${id}-trigger`} ref={trigger} type="button" className="filter-dropdown__trigger"
      aria-label={`${label}: ${summary}`} aria-haspopup="dialog" aria-expanded={open}
      aria-controls={open ? id : undefined}>
      <span>{summary}</span>
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </button>
  </Popover></div>
}
