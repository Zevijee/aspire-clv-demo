/** A row of buttons choosing one view of the same content, such as one category
 * of a breakdown. Exactly one is selected; it reads as pressed to assistive
 * technology. Wraps onto further lines at narrow widths rather than scrolling.
 *
 * With `values` instead of `value` it chooses several: each button toggles
 * its own id through onChange, and every selected one reads as pressed. The
 * caller decides what an empty selection means and may show it as a
 * selected "All" option. */
export function SegmentedControl({ label, options, value, values, onChange, fullWidth = false, separate = false,
  tone = 'primary' }: {
  /** What is being chosen, for screen readers: the strip has no visible title. */
  label: string
  options: readonly { id: string; label: string }[]
  /** The one selected id. */
  value?: string
  /** The selected ids, for a control that chooses several. */
  values?: readonly string[]
  /** The id chosen, or in a several-choice control, the id to toggle. */
  onChange: (id: string) => void
  /** Span the available width, the buttons sharing it equally. */
  fullWidth?: boolean
  /** Each option its own bordered button with space between, not one strip. */
  separate?: boolean
  /** Accent (orange) for a control on a blue surface, where primary would vanish. */
  tone?: 'primary' | 'accent'
}) {
  const selected = (id: string) => values ? values.includes(id) : id === value
  return <div className={`segmented-control${fullWidth ? ' segmented-control--full-width' : ''}${
    separate ? ' segmented-control--separate' : ''}${tone === 'accent' ? ' segmented-control--accent' : ''}`}
    role="group" aria-label={label}>
    {options.map(option => <button key={option.id} type="button"
      className={`segmented-control__option${selected(option.id) ? ' segmented-control__option--selected' : ''}`}
      aria-pressed={selected(option.id)} onClick={() => onChange(option.id)}>
      {option.label}
    </button>)}
  </div>
}
