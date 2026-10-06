/** A row of buttons choosing one view of the same content, such as one category
 * of a breakdown. Exactly one is selected; it reads as pressed to assistive
 * technology. Wraps onto further lines at narrow widths rather than scrolling. */
export function SegmentedControl({ label, options, value, onChange, fullWidth = false }: {
  /** What is being chosen, for screen readers: the strip has no visible title. */
  label: string
  options: readonly { id: string; label: string }[]
  value: string
  onChange: (id: string) => void
  /** Span the available width, the buttons sharing it equally. */
  fullWidth?: boolean
}) {
  return <div className={`segmented-control${fullWidth ? ' segmented-control--full-width' : ''}`}
    role="group" aria-label={label}>
    {options.map(option => <button key={option.id} type="button"
      className={`segmented-control__option${option.id === value ? ' segmented-control__option--selected' : ''}`}
      aria-pressed={option.id === value} onClick={() => onChange(option.id)}>
      {option.label}
    </button>)}
  </div>
}
