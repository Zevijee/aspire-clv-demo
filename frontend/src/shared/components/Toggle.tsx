/** A toggle. Two forms:
 *
 * - offLabel / onLabel: a choice between two values, drawn as a pill -- a
 *   light track with the value in effect raised as a white chip, "Stay start |
 *   ARD". Each value is a button with aria-pressed, in a labelled group.
 * - label: one setting, on or off, drawn as a switch -- "Active only". A button
 *   with role="switch" and aria-checked.
 *
 * Both are keyboard and screen-reader operable. For three or more options, use
 * SegmentedControl. */
export function Toggle({ checked, onChange, label, offLabel, onLabel, ariaLabel, heading }: {
  checked: boolean
  onChange: (checked: boolean) => void
  /** One setting's name, shown beside the switch. */
  label?: string
  /** The two values' names: off is first, on second. */
  offLabel?: string
  onLabel?: string
  /** What the toggle decides, for screen readers -- "Date range applies to". */
  ariaLabel?: string
  /** A small label above the two-value toggle, laid out like the header
   * filters' labels ("Date range") so it lines up beside them. */
  heading?: string
}) {
  if (offLabel !== undefined && onLabel !== undefined) {
    const pill = <span className="toggle-pill" role="group" aria-label={ariaLabel ?? heading ?? `${offLabel} or ${onLabel}`}>
      {[[false, offLabel], [true, onLabel]].map(([value, text]) =>
        <button key={String(value)} type="button" aria-pressed={checked === value}
          className={`toggle-pill__option${checked === value ? ' toggle-pill__option--active' : ''}`}
          onClick={() => onChange(value as boolean)}>{text}</button>)}
    </span>
    return heading === undefined ? pill
      : <div className="toggle-field"><span className="toggle-field__label" aria-hidden="true">{heading}</span>{pill}</div>
  }
  return <span className="toggle">
    <button type="button" role="switch" aria-checked={checked} aria-label={ariaLabel ?? label}
      className={`toggle__switch${checked ? ' toggle__switch--on' : ''}`} onClick={() => onChange(!checked)}>
      <span className="toggle__thumb" aria-hidden="true" />
    </button>
    {label && <span className="toggle__label" aria-hidden="true" onClick={() => onChange(!checked)}>{label}</span>}
  </span>
}
