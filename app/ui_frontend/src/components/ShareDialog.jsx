// Share a lecture read-only with another account: pick a user from the
// dropdown and press Share. Accounts that already have it are listed
// underneath, each with a Remove link. Owner or admin only.
import { useState, useEffect } from 'react'

function ShareDialog({ lecture, onSave, onClose }) {
  const [users, setUsers] = useState(null) // [{ username, is_demo }]
  const [shared, setShared] = useState([]) // usernames that already have access
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/auth/users/names').then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))),
      fetch(`/api/sessions/${lecture.id}/shares`).then(r => (r.ok ? r.json() : { usernames: [] })),
    ])
      .then(([names, shares]) => {
        setUsers(names.filter(u => u.username !== lecture.owner))
        setShared(shares.usernames)
      })
      .catch(err => setError(`Could not load users: ${err.message}`))
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lecture.id, lecture.owner, onClose])

  const available = (users || []).filter(u => !shared.includes(u.username))

  const save = async (usernames) => {
    setBusy(true)
    setError(null)
    try {
      await onSave(usernames)
      setShared(usernames)
      setPick('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const share = (e) => {
    e.preventDefault()
    if (pick) save([...shared, pick])
  }

  const remove = (username) => save(shared.filter(u => u !== username))

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <form className="dialog" role="dialog" aria-labelledby="share-title" onClick={e => e.stopPropagation()} onSubmit={share}>
        <h2 id="share-title">Share lecture</h2>
        <p className="dialog-subtitle">{lecture.title || 'Untitled lecture'}</p>
        <p className="dialog-message">
          Read-only: they can view the transcript and notes, ask their own questions and export, but not change anything.
        </p>
        <label className="dialog-field">
          Share with
          <select value={pick} onChange={e => setPick(e.target.value)} disabled={users === null || busy}>
            <option value="">
              {users === null ? 'Loading users…' : available.length ? 'Choose a user…' : 'No other accounts to share with'}
            </option>
            {available.map(u => (
              <option key={u.username} value={u.username}>{u.username}{u.is_demo ? ' (demo account)' : ''}</option>
            ))}
          </select>
        </label>
        {shared.length > 0 && (
          <div className="share-list">
            {shared.map(username => (
              <div key={username} className="share-row">
                <span>{username}</span>
                <button type="button" className="link-button share-remove" onClick={() => remove(username)} disabled={busy}>Remove</button>
              </div>
            ))}
          </div>
        )}
        {error && <p className="settings-inline-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>Close</button>
          <button type="submit" className="btn-primary" disabled={busy || !pick}>{busy ? 'Saving…' : 'Share'}</button>
        </div>
      </form>
    </div>
  )
}

export default ShareDialog
