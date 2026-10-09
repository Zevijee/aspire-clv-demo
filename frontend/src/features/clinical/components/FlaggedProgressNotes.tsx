import { Fragment, useCallback, useEffect, useState } from 'react'
import { DetailModal } from '../../../shared/components/DetailModal'
import { LocationName } from '../../../shared/components/LocationName'
import { Table, type TableColumn } from '../../../shared/components/Table'
import { Tag, TagList, TagMark } from '../../../shared/components/Tag'
import {
  downloadFlaggedNotes, flaggedNotesBase, getFlaggedNotes, type FlaggedNote, type FlaggedNotesQuery,
} from '../api'

const pageSize = 50
const dateFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
})
const day = (value: string) => dateFormat.format(new Date(`${value}T00:00:00Z`))
const longDate = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

// Column ids match the API's allowlist exactly: sorting and filtering are done by
// the server, so a name that does not match is silently unsortable.
const columns: TableColumn<FlaggedNote>[] = [
  { id: 'resident', header: 'Resident', isRowHeader: true, value: row => row.resident_name },
  { id: 'note-date', header: 'Date', initialSortDirection: 'descending', value: row => row.note_date,
    format: (_, row) => day(row.note_date) },
  { id: 'facility', header: 'Facility', filterable: true, value: row => row.facility_name,
    format: (_, row) => <LocationName region={row.region} portfolio={row.portfolio} state={row.state}>
      {row.facility_name}</LocationName> },
  { id: 'state', header: 'State', filterable: true, hidden: true, value: row => row.state },
  { id: 'portfolio', header: 'Portfolio', filterable: true, hidden: true, value: row => row.portfolio },
  { id: 'region', header: 'Region', filterable: true, hidden: true, value: row => row.region },
  { id: 'note-type', header: 'Note type', filterable: true, value: row => row.note_type },
  { id: 'payer', header: 'Payer', filterable: true, value: row => row.payer_type },
  { id: 'clinician', header: 'Clinician', filterable: true, value: row => row.clinician },
  // Never cut: every flagged word shows, on one line.
  { id: 'flag-terms', header: 'Flag terms', filterable: true, truncate: false, value: row => row.flag_terms.join(', '),
    format: (_, row) => <TagList values={row.flag_terms} /> },
]

/** The note's text with each flagged word marked in its tag's colour, matched
 * as the seeder found them: whole words, any case. */
function MarkedText({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>
  // Longest first, so "septicemia" is marked whole rather than as "septic".
  const pattern = [...terms].sort((a, b) => b.length - a.length)
    .map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const parts = text.split(new RegExp(`\\b(${pattern})\\b`, 'gi'))
  // split keeps the matches at the odd positions.
  return <>{parts.map((part, index) => index % 2
    ? <TagMark key={index} term={terms.find(term => term.toLowerCase() === part.toLowerCase()) ?? part}>{part}</TagMark>
    : <Fragment key={index}>{part}</Fragment>)}</>
}

function NoteDetail({ note }: { note: FlaggedNote }) {
  return <div className="progress-note">
    <p className="progress-note__meta">Clinician: {note.clinician} · Payer: {note.payer_type}</p>
    <div className="progress-note__flags">Flags:{note.flag_terms.map(term => <Tag key={term}>{term}</Tag>)}</div>
    <p className="progress-note__text"><MarkedText text={note.note_text} terms={note.flag_terms} /></p>
  </div>
}

/** Flagged Progress Notes: every note from the last 10 days with a watch word in
 * it, paged, sorted and filtered by the API. A row opens the full note. */
export function FlaggedProgressNotes() {
  const [query, setQuery] = useState<FlaggedNotesQuery>({ filters: {}, sort: null, search: '' })
  const queryKey = JSON.stringify(query)
  const [page, setPage] = useState({ queryKey: '', index: 0 })
  const pageIndex = page.queryKey === queryKey ? page.index : 0
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([queryKey, pageIndex, retry])
  const [response, setResponse] = useState<{ key: string; items: FlaggedNote[]; total: number } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [open, setOpen] = useState<FlaggedNote | null>(null)
  const onQueryChange = useCallback((next: FlaggedNotesQuery) => {
    setQuery(current => JSON.stringify(current) === JSON.stringify(next) ? current : next)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getFlaggedNotes(pageIndex * pageSize, query, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResponse({ key: requestKey, items: data.items, total: data.total })
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: error.message })
      })
    return () => controller.abort()
  }, [pageIndex, query, requestKey])

  const result = response?.key === requestKey ? response : null
  const error = failure?.key === requestKey ? failure.message : null
  const status = { loading: result === null && error === null, error,
    onRetry: () => setRetry(count => count + 1) }
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize))
  return <>
    <Table<FlaggedNote> {...status}
      title="Flagged note log"
      subtitle="Progress notes from the last 10 days containing a watch word. Select a note to read it in full."
      columns={columns} rows={result?.items ?? []} getRowKey={row => row.note_id}
      initialSort={{ columnId: 'note-date', direction: 'descending' }}
      internalScroll stickyFirstColumn searchable serverSide clearableFilters
      filterSource={{ id: 'flagged-notes', startDate: '', endDate: '', endpoint: `${flaggedNotesBase}/filter-options` }}
      onQueryChange={onQueryChange} totalRows={result?.total} onRowClick={setOpen}
      emptyMessage="No flagged notes match these filters."
      csvFileName="flagged-notes.csv"
      onExport={() => downloadFlaggedNotes(query)}
      footer={<nav aria-label="Note pagination" className="report-table__pagination">
        <span className="report-table__pagination-summary" role="status" aria-live="polite">
          {result ? `Page ${pageIndex + 1} of ${pageCount} — ${result.total.toLocaleString()} notes`
            : error ? 'Pagination unavailable' : 'Loading notes…'}
        </span>
        <div className="report-table__pagination-actions">
          {[
            { label: 'First page', symbol: '«', index: 0, disabled: pageIndex === 0 },
            { label: 'Previous page', symbol: '‹', index: pageIndex - 1, disabled: pageIndex === 0 },
            { label: 'Next page', symbol: '›', index: pageIndex + 1, disabled: pageIndex + 1 >= pageCount },
            { label: 'Last page', symbol: '»', index: pageCount - 1, disabled: pageIndex + 1 >= pageCount },
          ].map(({ label, symbol, index, disabled }) => <button key={label} type="button"
            className="report-table__pagination-arrow" aria-label={label} title={label}
            disabled={status.loading || !!error || disabled} onClick={() => setPage({ queryKey, index })}>
            <span aria-hidden="true">{symbol}</span>
          </button>)}
        </div>
      </nav>}
    />
    <DetailModal open={open !== null} onClose={() => setOpen(null)} title={open?.resident_name}
      subtitle={open && `${open.facility_name} · ${longDate.format(new Date(`${open.note_date}T00:00:00Z`))} · ${open.note_type}`}>
      {open && <NoteDetail note={open} />}
    </DetailModal>
  </>
}
