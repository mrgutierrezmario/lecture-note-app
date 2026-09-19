// Admin user management: list, add, reset password, set quota, delete.
import { useState, useEffect, useCallback } from 'react'
import { TrashIcon, KeyIcon, AudioIcon } from './Icons'
import { useDialog } from './Dialog'

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
  return data
}

function UsersSection({ currentUser }) {
  const dialog = useDialog()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [isDemo, setIsDemo] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setUsers(await api('/api/auth/users'))
      setError(null)
    } catch (err) {
      setError(`Could not load users: ${err.message}`)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const create = (e) => {
    e.preventDefault()
    run(async () => {
      await api('/api/auth/users', { method: 'POST', body: JSON.stringify({ username, email: email || null, password, is_admin: isAdmin, is_demo: isDemo }) })
      setUsername(''); setEmail(''); setPassword(''); setIsAdmin(false); setIsDemo(false)
    })
  }

  const resetPassword = async (u) => {
    const next = await dialog.prompt({ title: `Reset password for ${u.username}`, label: 'New password (min 8 characters)', type: 'password', confirmLabel: 'Set password' })
    if (!next) return
    run(() => api(`/api/auth/users/${u.id}/password`, { method: 'POST', body: JSON.stringify({ new_password: next }) }))
  }

  const setQuota = async (u) => {
    const answer = await dialog.prompt({ title: `Storage quota for ${u.username}`, label: 'MB of audio (0 = unlimited, blank = default)', defaultValue: u.quota_mb ?? '', confirmLabel: 'Save' })
    if (answer === null) return
    const body = answer.trim() === '' ? { clear_quota: true } : { quota_mb: Number(answer) }
    if (!body.clear_quota && (!Number.isInteger(body.quota_mb) || body.quota_mb < 0)) {
      setError('Quota must be a whole number of MB')
      return
    }
    run(() => api(`/api/auth/users/${u.id}`, { method: 'PATCH', body: JSON.stringify(body) }))
  }

  const remove = async (u) => {
    const ok = await dialog.confirm({
      title: `Delete ${u.username}?`,
      message: 'They will no longer be able to sign in. Their lectures are kept and become admin-only. This can\'t be undone.',
      confirmLabel: 'Delete user',
      danger: true,
    })
    if (!ok) return
    run(() => api(`/api/auth/users/${u.id}`, { method: 'DELETE' }))
  }

  return (
    <section className="settings-section">
      <h3>Users</h3>
      {error && <p className="settings-inline-error">{error}</p>}

      {users && (
        <ul className="user-list">
          {users.map(u => (
            <li key={u.id} className="user-row">
              <span className="user-row-name">
                <span className="user-row-id">
                  {u.username}
                  {u.email && <span className="user-row-email">{u.email}</span>}
                </span>
                {u.is_admin && <span className="user-badge">admin</span>}
                {u.is_demo && <span className="user-badge user-badge-you" data-tip="Read-only demo account ('Try the demo' on the sign-in page)">demo</span>}
                {u.email_verified === false && <span className="user-badge user-badge-warn" data-tip="Signed up but hasn't opened the confirmation email yet">unverified</span>}
                {u.approved === false && <span className="user-badge user-badge-warn" data-tip="Waiting for an admin to approve the account">pending</span>}
                {u.id === currentUser.id && <span className="user-badge user-badge-you">you</span>}
                {u.quota_mb != null && <span className="user-badge user-badge-you">{u.quota_mb === 0 ? 'unlimited' : `${u.quota_mb} MB`}</span>}
              </span>
              <span className="user-row-actions">
                <button className="btn-icon" onClick={() => setQuota(u)} disabled={busy} data-tip="Storage quota" aria-label={`Set storage quota for ${u.username}`}>
                  <AudioIcon size={16} />
                </button>
                {u.approved === false && (
                  <button className="btn-approve" onClick={() => run(() => api(`/api/auth/users/${u.id}/approve`, { method: 'POST' }))} disabled={busy} data-tip="Activate this account and email the user">
                    Approve
                  </button>
                )}
                <button className="btn-icon" onClick={() => resetPassword(u)} disabled={busy} data-tip="Reset password" aria-label={`Reset password for ${u.username}`}>
                  <KeyIcon size={16} />
                </button>
                <button className="btn-icon" onClick={() => remove(u)} disabled={busy || u.id === currentUser.id} data-tip="Delete user" aria-label={`Delete ${u.username}`}>
                  <TrashIcon size={16} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form className="user-create" onSubmit={create}>
        <input
          type="text"
          placeholder="username"
          value={username}
          onChange={e => setUsername(e.target.value)}
          autoCapitalize="none"
          autoComplete="off"
          required
        />
        <input
          type="email"
          placeholder="email (optional)"
          value={email}
          onChange={e => setEmail(e.target.value)}
          autoComplete="off"
        />
        <input
          type="password"
          placeholder="password (min 8)"
          value={password}
          onChange={e => setPassword(e.target.value)}
          autoComplete="new-password"
          minLength={8}
          required
        />
        <label className="switch">
          <input type="checkbox" checked={isAdmin} disabled={isDemo} onChange={e => setIsAdmin(e.target.checked)} />
          <span className="switch-track" />
          Admin
        </label>
        <label className="switch" data-tip="A read-only visitor account: 'Try the demo' on the sign-in page signs into it without a password. It can open its lectures and ask questions, nothing else.">
          <input type="checkbox" checked={isDemo} disabled={isAdmin} onChange={e => setIsDemo(e.target.checked)} />
          <span className="switch-track" />
          Demo
        </label>
        <button type="submit" className="btn-primary user-create-submit" disabled={busy || !username || !password}>
          Add user
        </button>
      </form>
      <p className="settings-note user-create-note">
        Admins can change models and credentials and manage users. Everyone else can record and review their own lectures.
        A demo account is read-only: assign it a lecture or two (History → the person icon) and visitors can look around without signing up.
      </p>
    </section>
  )
}

export default UsersSection
