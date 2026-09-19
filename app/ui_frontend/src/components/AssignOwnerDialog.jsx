// Admin: hand a lecture to another account — a dropdown of the registered
// users rather than a free-text username (the demo account is marked).
import { useState, useEffect, useRef } from 'react'

function AssignOwnerDialog({ lecture, currentOwner, onAssign, onClose }) {
  const [users, setUsers] = useState(null)
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const selectRef = useRef(null)

  useEffect(() => {
    fetch('/api/auth/users')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(rows => {
        const others = rows.filter(u => u.username !== currentOwner && !u.disabled)
        setUsers(others)
        setChoice(others[0]?.username || '')
        setTimeout(() => selectRef.current?.focus(), 0)
      })
      .catch(err => setError(`Could not load users: ${err.message}`))
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [currentOwner, onClose])

  const submit = async (e) => {
    e.preventDefault()
    if (!choice) return
    setBusy(true)
    setError(null)
    try {
      await onAssign(choice)
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const label = u => `${u.username}${u.is_demo ? ' — demo account' : u.is_admin ? ' — admin' : ''}${u.email ? ` (${u.email})` : ''}`

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <form className="dialog" role="dialog" aria-labelledby="assign-title" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 id="assign-title">Assign lecture</h2>
        <p className="dialog-message">
          Move <strong>{lecture.title || 'Untitled lecture'}</strong> to another account. It disappears from
          {currentOwner ? ` ${currentOwner}'s` : ' its current'} History and appears in theirs.
        </p>
        <label className="dialog-field">
          <span>New owner</span>
          {users === null && !error ? (
            <select disabled><option>Loading users…</option></select>
          ) : (
            <select ref={selectRef} value={choice} onChange={e => setChoice(e.target.value)} disabled={!users?.length}>
              {users?.length ? users.map(u => <option key={u.id} value={u.username}>{label(u)}</option>) : <option>No other users</option>}
            </select>
          )}
        </label>
        {error && <p className="settings-inline-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy || !choice}>{busy ? 'Assigning…' : 'Assign'}</button>
        </div>
      </form>
    </div>
  )
}

export default AssignOwnerDialog
