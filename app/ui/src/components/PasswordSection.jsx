// "Your account" in Settings: change your email and your password.
import { useState } from 'react'

function PasswordSection({ user, onUserChange }) {
  const [email, setEmail] = useState(user?.email || '')
  const [emailStatus, setEmailStatus] = useState(null)
  const [emailBusy, setEmailBusy] = useState(false)

  const saveEmail = async (e) => {
    e.preventDefault()
    setEmailBusy(true)
    setEmailStatus(null)
    try {
      const response = await fetch('/api/auth/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      setEmailStatus({ ok: true, text: 'Email saved.' })
      onUserChange?.(data)
    } catch (err) {
      setEmailStatus({ ok: false, text: err.message })
    } finally {
      setEmailBusy(false)
    }
  }
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [status, setStatus] = useState(null) // { ok, text }
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (next !== repeat) {
      setStatus({ ok: false, text: 'New passwords do not match' })
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      const response = await fetch('/api/auth/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: current, new_password: next }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${response.status}`)
      }
      setStatus({ ok: true, text: 'Password changed.' })
      setCurrent(''); setNext(''); setRepeat('')
    } catch (err) {
      setStatus({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="settings-section">
      <h3>Your account</h3>
      <form onSubmit={saveEmail}>
        <label className="settings-field">
          <span>Username</span>
          <input type="text" value={user?.username || ''} disabled />
        </label>
        <label className="settings-field">
          <span>Email</span>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" placeholder="you@example.com" />
        </label>
        <p className="settings-note">You can sign in with either your username or your email.</p>
        {emailStatus && <p className={emailStatus.ok ? 'settings-inline-ok' : 'settings-inline-error'}>{emailStatus.text}</p>}
        <div className="settings-actions">
          <button type="submit" disabled={emailBusy || email === (user?.email || '')}>
            {emailBusy ? 'Saving…' : 'Save email'}
          </button>
        </div>
      </form>

      <h3 className="settings-subheading">Change password</h3>
      <form onSubmit={submit}>
        <label className="settings-field">
          <span>Current password</span>
          <input type="password" value={current} onChange={e => setCurrent(e.target.value)} autoComplete="current-password" required />
        </label>
        <label className="settings-field">
          <span>New password</span>
          <input type="password" value={next} onChange={e => setNext(e.target.value)} autoComplete="new-password" minLength={8} required />
        </label>
        <label className="settings-field">
          <span>Repeat new password</span>
          <input type="password" value={repeat} onChange={e => setRepeat(e.target.value)} autoComplete="new-password" minLength={8} required />
        </label>
        {status && <p className={status.ok ? 'settings-inline-ok' : 'settings-inline-error'}>{status.text}</p>}
        <div className="settings-actions">
          <button type="submit" disabled={busy || !current || !next || !repeat}>
            {busy ? 'Saving…' : 'Change password'}
          </button>
        </div>
      </form>
    </section>
  )
}

export default PasswordSection
