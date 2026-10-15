/** A figure of a table row worked out once per row object, however many columns
 * and sort comparisons ask for it: Monthly Staffing Trending's columns each sum
 * a row's facilities over every month, and sorting asks again and again -- the
 * Show all facilities table's 253 rows spent a quarter of a second on it. Made
 * afresh each render, so it never outlives the data it was worked out from. */
export function perRow<Row extends object, Value>(compute: (row: Row) => Value) {
  const kept = new WeakMap<Row, Value>()
  return (row: Row) => {
    if (kept.has(row)) return kept.get(row) as Value
    const value = compute(row)
    kept.set(row, value)
    return value
  }
}
