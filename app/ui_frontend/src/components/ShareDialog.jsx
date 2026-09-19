// Share a lecture read-only with other accounts: a checkbox per registered
// user (tick to share, untick to remove access). Owner or admin only.
import { useState, useEffect } from 'react'

function ShareDialog({ lecture, onSave, onClose }) {
  const [users, setUsers] = useState(null) // [{ username, is_demo }]
  const [chosen, setChosen] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/auth/users/names').then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))),
      fetch(`/api/sessions/${lecture.id}/shares`).then(r => (r.ok ? r.json() : { usernames: [] })),
    ])
      .then(([names, shares]) => {
        setUsers(names.filter(u => u.username !== lecture.owner))
        setChosen(new Set(shares.usernames))
      })
      .catch(err => setError(`Could not load users: ${err.message}`))
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lecture.id, lecture.owner, onClose])

  const toggle = (username) => setChosen(prev => {
    const next = new Set(prev)
    if (next.has(username)) next.delete(username); else next.add(username)
    return next
  })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSave([...chosen])
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <form className="dialog" role="dialog" aria-labelledby="share-title" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 id="share-title">Share lecture</h2>
        <p className="dialog-message">
          People you tick see <strong>{lecture.title || 'this lecture'}</strong> in their History: transcript, notes,
          their own questions, exports. Only you can change it. Untick to remove access.
        </p>
        <div className="share-list">
          {users === null && !error && <p className="settings-note settings-note-full">Loading users…</p>}
          {users?.length === 0 && <p className="settings-note settings-note-full">There are no other accounts to share with yet.</p>}
          {users?.map(u => (
            <label key={u.username} className="share-row">
              <input type="checkbox" checked={chosen.has(u.username)} onChange={() => toggle(u.username)} />
              <span>{u.username}</span>
              {u.is_demo && <span className="user-badge user-badge-you" data-tip="The read-only demo account — share here to make this lecture visible to 'Try the demo' visitors">demo</span>}
            </label>
          ))}
        </div>
        {error && <p className="settings-inline-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy || users === null}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </div>
  )
}

export default ShareDialog
