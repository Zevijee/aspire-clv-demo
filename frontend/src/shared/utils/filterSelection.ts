/** Bulk actions affect shown options only, preserving selections outside the current list. */
export function toggleShownValues(selected: string[], shown: string[]): string[] {
  if (!shown.length) return selected
  return shown.every((value) => selected.includes(value))
    ? selected.filter((value) => !shown.includes(value)) : [...new Set([...selected, ...shown])]
}
