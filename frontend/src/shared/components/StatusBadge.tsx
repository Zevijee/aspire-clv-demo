export type StatusTone = 'danger' | 'warning' | 'success' | 'neutral'

/** A short status word in a coloured pill, such as Outbreak or Watch: danger
 * for what needs action now, warning for what needs watching. For Yes/No use
 * BooleanBadge, which Table applies by itself. */
export function StatusBadge({ tone, compact = false, children }: {
  tone: StatusTone
  /** Smaller, for a badge that sits beneath the value it qualifies. */
  compact?: boolean
  children: string
}) {
  return <span className={`boolean-badge status-badge--${tone}${compact ? ' status-badge--compact' : ''}`}>
    {children}</span>
}
