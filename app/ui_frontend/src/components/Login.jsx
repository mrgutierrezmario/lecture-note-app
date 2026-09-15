/**
 * Sign-in screen with three modes: sign in (username or email), create an
 * account (when the admin has left registration open), and forgot password
 * (when outgoing email is configured). Which extras appear comes from
 * `/api/auth/status`, which needs no login.
 */
import { useState, useEffect } from 'react'

function Login({ onLogin, onRegister }) {
  const [mode, setMode] = useState('login') // 'login' | 'register' | 'forgot'
  const [registrationOpen, setRegistrationOpen] = useState(false)
  const [resetAvailable, setResetAvailable] = useState(false)
  const [sent, setSent] = useState(false)
  const [identifier, setIdentifier] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(null) // registration done, waiting for the emailed link
  const [needsVerify, setNeedsVerify] = useState(false) // login refused: email not confirmed
  const [resent, setResent] = useState(false)

  useEffect(() => {
    fetch('/api/auth/status')
      .then(r => (r.ok ? r.json() : {}))
      .then(d => { setRegistrationOpen(Boolean(d.registration_open)); setResetAvailable(Boolean(d.password_reset_available)) })
      .catch(() => { setRegistrationOpen(false); setResetAvailable(false) })
  }, [])

  const switchMode = (next) => { setMode(next); setError(null); setPassword(''); setRepeat(''); setSent(false); setPending(null); setNeedsVerify(false); setResent(false) }

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (mode === 'register' && password !== repeat) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    setNeedsVerify(false)
    try {
      if (mode === 'login') await onLogin(identifier.trim(), password)
      else if (mode === 'forgot') {
        await fetch('/api/auth/forgot', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ identifier: identifier.trim() }),
        })
        setSent(true)
      }
      else {
        const result = await onRegister(username.trim(), email.trim(), password)
        if (result?.pending_verification) { setPending(result); setIdentifier(username.trim()) }
      }
    } catch (err) {
      setError(err.message)
      if (err.code === 'verification_required') setNeedsVerify(true)
    } finally {
      setBusy(false)
    }
  }

  const resend = async () => {
    setBusy(true)
    try {
      await fetch('/api/auth/verify/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: (identifier || pending?.email || '').trim() }),
      })
      setResent(true)
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = mode === 'login'
    ? identifier && password
    : mode === 'forgot'
      ? identifier
      : username && email && password && repeat

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <img className="login-logo" src="/logo-mark.svg" alt="M.G. Network and Technology Solutions" />
        <h1>AI Lecture Notes</h1>
        <p className="login-sub">
          {mode === 'login' ? 'Sign in to record and review lectures'
            : mode === 'forgot' ? 'Reset your password'
            : 'Create your account'}
        </p>

        {pending ? (
          <>
            <p className="login-sent">{pending.message}</p>
            <p className="login-note">
              {resent
                ? 'Sent again.'
                : <>Didn't get it? <button type="button" className="link-button" disabled={busy} onClick={resend}>Send it again</button></>}
              {' · '}<button type="button" className="link-button" onClick={() => switchMode('login')}>Back to sign in</button>
            </p>
          </>
        ) : mode === 'forgot' && sent ? (
          <p className="login-sent">
            If that account exists and has an email address, a reset link is on its way. It works for 60 minutes — check your spam folder if it doesn't show up.
          </p>
        ) : mode !== 'register' ? (
          <label className="login-field">
            <span>Username or email</span>
            <input
              type="text"
              value={identifier}
              onChange={e => setIdentifier(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoFocus
              required
            />
          </label>
        ) : (
          <>
            <label className="login-field">
              <span>Username</span>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                pattern="[A-Za-z0-9._-]{2,64}"
                title="2-64 letters, digits, dots, dashes or underscores"
                autoFocus
                required
              />
            </label>
            <label className="login-field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
                autoCapitalize="none"
                required
              />
            </label>
          </>
        )}

        {mode !== 'forgot' && (
        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={mode === 'register' ? 8 : undefined}
            required
          />
        </label>
        )}
        {mode === 'register' && (
          <label className="login-field">
            <span>Repeat password</span>
            <input
              type="password"
              value={repeat}
              onChange={e => setRepeat(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </label>
        )}

        {error && !pending && (
          <p className="login-error">
            {error}
            {needsVerify && (
              <> {resent
                ? 'Sent again — check your inbox.'
                : <button type="button" className="link-button" disabled={busy} onClick={resend}>Send the link again</button>}</>
            )}
          </p>
        )}

        {!(mode === 'forgot' && sent) && !pending && (
          <button type="submit" className="btn-primary login-submit" disabled={busy || !canSubmit}>
            {busy
              ? (mode === 'login' ? 'Signing in…' : mode === 'forgot' ? 'Sending…' : 'Creating account…')
              : (mode === 'login' ? 'Sign in' : mode === 'forgot' ? 'Email me a reset link' : 'Create account')}
          </button>
        )}

        {mode === 'forgot' ? (
          <p className="login-note">
            <button type="button" className="link-button" onClick={() => switchMode('login')}>Back to sign in</button>
          </p>
        ) : mode === 'login' ? (
          <p className="login-note">
            {registrationOpen ? (
              <>New here? <button type="button" className="link-button" onClick={() => switchMode('register')}>Create an account</button></>
            ) : (
              <>No account? Ask your administrator to create one.</>
            )}
            {resetAvailable && (
              <> · <button type="button" className="link-button" onClick={() => switchMode('forgot')}>Forgot password?</button></>
            )}
          </p>
        ) : (
          <p className="login-note">
            Already have an account? <button type="button" className="link-button" onClick={() => switchMode('login')}>Sign in</button>
          </p>
        )}
      </form>
    </div>
  )
}

export default Login
