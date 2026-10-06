/** A row of buttons choosing one view of the same content, such as one category
 * of a breakdown. Exactly one is selected; it reads as pressed to assistive
 * technology. Wraps onto further lines at narrow widths rather than scrolling. */
export function SegmentedControl({ label, options, value, onChange, fullWidth = false, separate = false,
  tone = 'primary' }: {
  /** What is being chosen, for screen readers: the strip has no visible title. */
  label: string
  options: readonly { id: string; label: string }[]
  value: string
  onChange: (id: string) => void
  /** Span the available width, the buttons sharing it equally. */
  fullWidth?: boolean
  /** Each option its own bordered button with space between, not one strip. */
  separate?: boolean
  /** Accent (orange) for a control on a blue surface, where primary would vanish. */
  tone?: 'primary' | 'accent'
}) {
  return <div className={`segmented-control${fullWidth ? ' segmented-control--full-width' : ''}${
    separate ? ' segmented-control--separate' : ''}${tone === 'accent' ? ' segmented-control--accent' : ''}`}
    role="group" aria-label={label}>
    {options.map(option => <button key={option.id} type="button"
      className={`segmented-control__option${option.id === value ? ' segmented-control__option--selected' : ''}`}
      aria-pressed={option.id === value} onClick={() => onChange(option.id)}>
      {option.label}
    </button>)}
  </div>
}
