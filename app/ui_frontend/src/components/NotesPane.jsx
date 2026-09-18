// Rendered Markdown of the latest notes version, with an empty state before the
// first generation pass. The notes can be edited in place (saved as a new
// version, so later passes build on the edit) and, for a lecture that is not
// recording, regenerated from the whole transcript — e.g. after setting a focus.
import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { NotesIcon, SparklesIcon, EditIcon, SpinnerIcon, CheckIcon, CloseIcon } from './Icons'
import { useDialog } from './Dialog'

function NotesPane({ notes, version, sessionId, isRecording, onNotesChange }) {
  const dialog = useDialog()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(null) // 'saving' | 'regenerating' | null

  // Leaving the lecture (new session) drops any unsaved edit.
  useEffect(() => { setEditing(false) }, [sessionId])

  const startEdit = () => { setDraft(notes || ''); setEditing(true) }

  const save = async () => {
    setBusy('saving')
    try {
      const response = await fetch(`/api/session/${sessionId}/notes`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes_md: draft }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      onNotesChange?.(data.notes_md, data.version)
      setEditing(false)
    } catch (err) {
      dialog.notice({ title: 'Could not save notes', message: err.message })
    } finally {
      setBusy(null)
    }
  }

  const regenerate = async () => {
    const ok = await dialog.confirm({
      title: 'Regenerate the notes?',
      message: 'The notes are rewritten from the whole transcript using the current lecture focus. Earlier versions stay in the history, but the new notes replace what you see here. This can take a minute for a long lecture.',
      confirmLabel: 'Regenerate',
    })
    if (!ok) return
    setBusy('regenerating')
    try {
      const response = await fetch(`/api/session/${sessionId}/notes/regenerate`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      onNotesChange?.(data.notes_md, data.version)
    } catch (err) {
      dialog.notice({ title: 'Could not regenerate', message: err.message })
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="pane">
      <header className="pane-header">
        <div className="pane-title">
          <span className="pane-icon pane-icon-teal"><NotesIcon /></span>
          <h2>Notes</h2>
        </div>
        <span className="pane-meta pane-actions">
          {busy === 'regenerating' ? (
            <><SpinnerIcon size={14} /> Regenerating…</>
          ) : editing ? (
            <>
              <button className="btn-icon" onClick={() => setEditing(false)} disabled={busy === 'saving'} data-tip="Discard changes" aria-label="Cancel editing"><CloseIcon size={14} /></button>
              <button className="btn-icon btn-icon-active" onClick={save} disabled={busy === 'saving'} data-tip="Save as a new version" aria-label="Save notes">
                {busy === 'saving' ? <SpinnerIcon size={14} /> : <CheckIcon size={14} />}
              </button>
            </>
          ) : (
            <>
              {version > 0 ? `Version ${version}` : 'Generated while you record'}
              {notes && (
                <button className="btn-icon" onClick={startEdit} data-tip="Edit the notes (saved as a new version; later passes build on your edit)" aria-label="Edit notes"><EditIcon size={14} /></button>
              )}
              {notes && !isRecording && (
                <button className="btn-icon" onClick={regenerate} data-tip="Rewrite the notes from the whole transcript with the current focus" aria-label="Regenerate notes"><SparklesIcon size={14} /></button>
              )}
            </>
          )}
        </span>
      </header>
      <div className="pane-body">
        {editing ? (
          <textarea className="notes-editor" value={draft} onChange={e => setDraft(e.target.value)} spellCheck="true" />
        ) : notes ? (
          <div className="notes-content">
            <ReactMarkdown>{notes}</ReactMarkdown>
          </div>
        ) : (
          <div className="empty-state">
            <span className="empty-icon"><SparklesIcon size={22} /></span>
            <strong>Notes will build as you record</strong>
            <p>Structured headings and bullet points are generated from the transcript automatically.</p>
          </div>
        )}
      </div>
    </section>
  )
}

export default NotesPane
