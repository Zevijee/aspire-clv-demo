export type FavorableChange = 'increase' | 'decrease' | 'neutral'

export function tableChange(value: number | string | null, favorable: FavorableChange) {
  const numeric = value === null || value === '' ? NaN : Number(value)
  if (!Number.isFinite(numeric)) return { text: value ?? '—', className: undefined }
  const isFavorable = favorable === 'increase' ? numeric > 0 : numeric < 0
  return {
    text: numeric === 0 ? '0' : `${numeric > 0 ? '+' : ''}${numeric.toLocaleString()}`,
    className: numeric === 0 || favorable === 'neutral' ? undefined
      : isFavorable ? 'report-table__change--favorable' : 'report-table__change--adverse',
  }
}
