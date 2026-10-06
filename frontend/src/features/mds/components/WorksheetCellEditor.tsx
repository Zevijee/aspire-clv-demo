import { Button, Input, InputNumber, Modal, Select } from 'antd'
import type { GetRef } from 'antd'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { DataState } from '../../../shared/components/DataState'
import {
  addWorksheetEntry, getWorksheetLog,
  type NewWorksheetEntry, type WorksheetEntry, type WorksheetField, type WorksheetRow,
} from '../worksheetApi'

type TextAreaRef = GetRef<typeof Input.TextArea>

const when = (value: string) => new Date(value).toLocaleString(undefined,
  { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

function describe(entry: WorksheetEntry) {
  // A Reply has no value: its note, shown below, is the whole entry.
  if (entry.action === 'set') return entry.label === null ? null : <>Set to <strong>{entry.label}</strong></>
  if (entry.action === 'add') return <>Added <strong>{entry.label}</strong></>
  if (entry.action === 'remove') return <>Removed <strong>{entry.label}</strong></>
  return null
}

/** One worksheet cell: enter a value with an optional note, and read and
 * answer everything entered on it before. Opens filled with what is there now,
 * so an entry is changed rather than retyped. Every save is appended to the
 * cell's log, so everyone sees who entered what and when. */
export function WorksheetCellEditor({ row, field, onClose, onSaved }: {
  row: WorksheetRow; field: WorksheetField; onClose: () => void; onSaved: () => void
}) {
  const [log, setLog] = useState<WorksheetEntry[] | null>(null)
  const [logError, setLogError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  // NTA opens on its picker, empty; every other cell on what it holds now.
  const opening = field.kind === 'diagnoses' ? undefined : row.cells[field.id]
  const [value, setValue] = useState<string | null>(opening?.value ?? null)
  const [note, setNote] = useState(opening?.note ?? '')
  const noteRef = useRef<TextAreaRef>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getWorksheetLog(row.payer_stay_id, field.id, controller.signal)
      .then(entries => { if (!controller.signal.aborted) { setLog(entries); setLogError(null) } })
      .catch((failure: Error) => { if (!controller.signal.aborted) setLogError(failure.message) })
    return () => controller.abort()
  }, [row.payer_stay_id, field.id, reload])

  const save = async (entry: NewWorksheetEntry, after: () => void) => {
    setSaving(true)
    setSaveError(null)
    try {
      await addWorksheetEntry(row.payer_stay_id, entry)
      after()
      setReload(count => count + 1)
      onSaved()
    } catch (failure) {
      setSaveError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const current = field.kind === 'diagnoses' ? null : row.cells[field.id]
  const chosen = new Set(row.nta.items.map(item => item.value))
  // What saving would replace: the cell's value, or the chosen diagnosis if
  // it is already on the list. Unchanged, there is nothing to save.
  const existing = field.kind === 'diagnoses' ? row.nta.items.find(item => item.value === value) : current
  const unchanged = existing !== undefined && existing !== null && existing.value === value
    && (existing.note ?? '') === note.trim()
  const editNote = (item: { value: string; note: string | null }) => {
    setValue(item.value)
    setNote(item.note ?? '')
    noteRef.current?.focus({ cursor: 'end' })
  }
  const entries = log ?? []
  const replies = (id: string) => entries.filter(entry => entry.reply_to === id)

  return <Modal open onCancel={onClose} footer={null} width={640} destroyOnHidden
    className="worksheet-editor" title={`${row.resident_name} · ${field.group === field.label ? field.label
      : `${field.group} ${field.label}`}`}>
    <div className="worksheet-editor__body">
      {field.kind === 'diagnoses' ? <section aria-label="NTA diagnoses" className="worksheet-editor__section">
        <p className="worksheet-editor__current">
          {row.nta.items.length ? `${row.nta.points} points · NTA ${row.nta.band}` : 'No diagnoses yet.'}
        </p>
        {row.nta.items.length > 0 && <ul className="worksheet-editor__diagnoses">
          {row.nta.items.map(item => <li key={item.value}>
            <span><strong>{item.label}</strong> · {item.points} pt{item.points === 1 ? '' : 's'}
              {item.note && <span className="worksheet-editor__note"> — {item.note}</span>}</span>
            <span className="worksheet-editor__item-actions">
              <Button size="small" disabled={saving} onClick={() => editNote(item)}>Edit note</Button>
              <Button size="small" disabled={saving}
                onClick={() => void save({ field: field.id, action: 'remove', value: item.value }, () => {
                  if (value === item.value) { setValue(null); setNote('') }
                })}>
                Remove
              </Button>
            </span>
          </li>)}
        </ul>}
        <label className="worksheet-editor__label" htmlFor="worksheet-diagnosis">
          {value !== null && chosen.has(value) ? 'Diagnosis' : 'Add a diagnosis'}</label>
        <Select id="worksheet-diagnosis" showSearch optionFilterProp="label" placeholder="Search diagnoses"
          value={value} style={{ width: '100%' }}
          onChange={next => { setValue(next); setNote(row.nta.items.find(item => item.value === next)?.note ?? '') }}
          options={(field.options ?? []).filter(option => !chosen.has(option.value) || option.value === value)
            .map(option => ({ value: option.value, label: `${option.label} (${option.points})` }))} />
      </section> : field.kind === 'text' ? null : <section aria-label="Value" className="worksheet-editor__section">
        <p className="worksheet-editor__current">
          {current ? <>Now <strong className={field.kind === 'hipps' ? 'care-code' : undefined}>{current.label}</strong>
            , by {current.author}, {when(current.created_at)}</> : 'Nothing entered yet.'}
        </p>
        <label className="worksheet-editor__label" htmlFor="worksheet-value">
          {field.kind === 'score' ? `${field.label} (${field.min}-${field.max})` : field.label}
        </label>
        {field.kind === 'choice' ? <Select id="worksheet-value" value={value} onChange={setValue}
          placeholder="Choose" style={{ width: '100%' }} options={field.options} />
          : field.kind === 'score' ? <InputNumber id="worksheet-value" min={field.min} max={field.max} precision={0}
            value={value === null ? null : Number(value)} style={{ width: '100%' }}
            onChange={next => setValue(next === null ? null : String(next))} />
          : <Input id="worksheet-value" maxLength={5} className="care-code" placeholder="e.g. KBCD1"
            value={value ?? ''} onChange={event => setValue(event.target.value.toUpperCase() || null)} />}
      </section>}
      {/* A Reply is only this text box; every other cell's note is optional. */}
      <label className="worksheet-editor__label" htmlFor="worksheet-note">
        {field.kind === 'text' ? field.label : 'Note (optional)'}</label>
      <Input.TextArea id="worksheet-note" ref={noteRef} rows={field.kind === 'text' ? 5 : 3} maxLength={4000}
        value={note} autoFocus={field.kind === 'text'}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setNote(event.target.value)} />
      {saveError && <p role="alert" className="worksheet-editor__error">{saveError}</p>}
      <div className="worksheet-editor__actions">
        {/* A diagnosis already on the list is added again with its new note,
            which replaces the old one; a new one is added. Other cells keep
            showing what was just saved, ready for the next change. */}
        <Button type="primary" loading={saving}
          disabled={(field.kind === 'text' ? !note.trim() : value === null) || unchanged}
          onClick={() => void save({ field: field.id, action: field.kind === 'diagnoses' ? 'add' : 'set',
            value, note: note.trim() || null }, () => {
            if (field.kind === 'diagnoses' && !chosen.has(value ?? '')) { setValue(null); setNote('') }
          })}>
          {field.kind !== 'diagnoses' ? 'Save' : value !== null && chosen.has(value) ? 'Save note' : 'Add diagnosis'}
        </Button>
      </div>

      <section aria-label="Log" className="worksheet-editor__log">
        <h3>Log</h3>
        {log === null ? <DataState loading={!logError} error={logError} onRetry={() => setReload(count => count + 1)}
          label="Log" /> : entries.filter(entry => entry.action !== 'reply').length === 0
          ? <p className="worksheet-editor__empty">No entries yet.</p>
          : <ol className="worksheet-editor__entries">
            {entries.filter(entry => entry.action !== 'reply').map(entry => <li key={entry.entry_id}>
              <p className="worksheet-editor__meta">{entry.author} · {when(entry.created_at)}</p>
              {describe(entry) && <p>{describe(entry)}</p>}
              {entry.note && <p className="worksheet-editor__note">{entry.note}</p>}
              {replies(entry.entry_id).length > 0 && <ol className="worksheet-editor__replies">
                {replies(entry.entry_id).map(answer => <li key={answer.entry_id}>
                  <p className="worksheet-editor__meta">{answer.author} · {when(answer.created_at)}</p>
                  <p className="worksheet-editor__note">{answer.note}</p>
                </li>)}
              </ol>}
            </li>)}
          </ol>}
      </section>
    </div>
  </Modal>
}
