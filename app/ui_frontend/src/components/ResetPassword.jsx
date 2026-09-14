// Landing page for the emailed reset link (/reset-password?token=…): choose a
// new password, then return to sign-in.
import { useState } from 'react'

// Landing page for the emailed link: /reset-password?token=…
function ResetPassword({ token, onDone }) {
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (password !== repeat) { setError('Passwords do not match'); return }
    setBusy(true)
    setError(null)
    try {
      const response = await fetch('/api/auth/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${response.status}`)
      }
      setDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <img className="login-logo" src="/logo-mark.svg" alt="M.G. Network and Technology Solutions" />
        <h1>Choose a new password</h1>
        {done ? (
          <>
            <p className="login-sent">Your password has been changed. You can sign in with it now.</p>
            <button type="button" className="btn-primary login-submit" onClick={onDone}>Go to sign in</button>
          </>
        ) : (
          <>
            <label className="login-field">
              <span>New password</span>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" minLength={8} autoFocus required />
            </label>
            <label className="login-field">
              <span>Repeat new password</span>
              <input type="password" value={repeat} onChange={e => setRepeat(e.target.value)} autoComplete="new-password" minLength={8} required />
            </label>
            {error && <p className="login-error">{error}</p>}
            <button type="submit" className="btn-primary login-submit" disabled={busy || !password || !repeat}>
              {busy ? 'Saving…' : 'Set new password'}
            </button>
            <p className="login-note">
              <button type="button" className="link-button" onClick={onDone}>Back to sign in</button>
            </p>
          </>
        )}
      </form>
    </div>
  )
}

export default ResetPassword
