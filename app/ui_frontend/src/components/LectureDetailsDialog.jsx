// "Lecture details" dialog: the two per-lecture hints — key terms for the
// transcriber and a focus for the notes generator. Opened from the "Aa" button
// next to the title; usable before, during and after a recording.
import { useState, useEffect, useRef } from 'react'

function LectureDetailsDialog({ vocabulary, notesFocus, onSave, onClose }) {
  const [terms, setTerms] = useState(vocabulary || '')
  const [focus, setFocus] = useState(notesFocus || '')
  const [busy, setBusy] = useState(false)
  const firstRef = useRef(null)

  useEffect(() => {
    firstRef.current?.focus()
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await onSave({ vocabulary: terms.trim(), notes_focus: focus.trim() })
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <form className="dialog dialog-wide" role="dialog" aria-labelledby="details-title" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 id="details-title">Lecture details</h2>
        <label className="dialog-field">
          <span>Key terms — names, acronyms, course terms (comma separated)</span>
          <input
            ref={firstRef}
            type="text"
            value={terms}
            placeholder="e.g. Porter's five forces, SWOT, Nvidia, Prof. Ramirez"
            onChange={e => setTerms(e.target.value)}
            autoComplete="off"
          />
          <small>The transcriber uses these to spell them right. Changes apply from the next chunk.</small>
        </label>
        <label className="dialog-field">
          <span>Notes focus — what the notes should emphasise</span>
          <input
            type="text"
            value={focus}
            placeholder="e.g. formulas and worked examples · case names and rulings · exam hints"
            onChange={e => setFocus(e.target.value)}
            maxLength={500}
            autoComplete="off"
          />
          <small>Applies to the next notes pass. For a finished lecture, use <em>Regenerate</em> in the Notes panel to rewrite with this focus.</small>
        </label>
        <div className="dialog-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </div>
  )
}

export default LectureDetailsDialog
