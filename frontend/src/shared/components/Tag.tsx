// The chart series colours, so tags sit in the same palette as the charts.
const TONES = 7

/** A tag's colour, 0-6, from its text: the same word, the same colour. */
export function toneOf(label: string) {
  let hash = 0
  for (const character of label.toLowerCase()) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return hash % TONES
}

/** A small coloured label for one of many values, such as a flagged word. The
 * colour follows the text, so the same word has the same colour wherever it
 * appears. For a status use StatusBadge; for Yes/No, BooleanBadge. */
export function Tag({ children }: { children: string }) {
  return <span className={`tag tag--${toneOf(children)}`}>{children}</span>
}

/** Several tags on one line, never stacked: the cell widens to fit them. */
export function TagList({ values }: { values: string[] }) {
  return <span className="tag-list">{values.map(value => <Tag key={value}>{value}</Tag>)}</span>
}

/** A word in running text marked in its tag's colour, so a highlight matches
 * the tag above it. */
export function TagMark({ children, term }: { children: string; term: string }) {
  return <mark className={`tag-mark tag--${toneOf(term)}`}>{children}</mark>
}
