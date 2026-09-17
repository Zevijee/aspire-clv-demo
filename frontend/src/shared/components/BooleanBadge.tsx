type BooleanBadgeProps = { value: boolean | null; negativeWhenTrue?: boolean }

export function BooleanBadge({ value, negativeWhenTrue = false }: BooleanBadgeProps) {
  return <span className={`boolean-badge boolean-badge--${value === null ? 'unknown' : negativeWhenTrue ? value ? 'negative' : 'positive' : value ? 'yes' : 'no'}`}>
    {value === null ? 'Unavailable' : value ? 'Yes' : 'No'}
  </span>
}
