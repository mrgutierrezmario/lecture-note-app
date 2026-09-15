/**
 * "Google Drive" in Settings, for every user: connect their own Google
 * account, choose whether each finished lecture is saved there automatically,
 * open the folder, disconnect. Connecting is a full-page redirect to Google
 * (/api/drive/connect → consent → /api/drive/callback → back here).
 */
import { useState, useEffect, useCallback } from 'react'
import { CheckIcon, AlertIcon, DriveIcon } from './Icons'
import { useDialog } from './Dialog'

// `refreshKey` changes when an admin saves/clears the OAuth client, so the section re-checks availability.
function DriveSection({ isAdmin, refreshKey }) {
  const dialog = useDialog()
  const [status, setStatus] = useState(null) // { available, connected, email, auto_export, folder_url }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/drive')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setStatus(await response.json())
    } catch (err) {
      setError(`Could not load Google Drive status: ${err.message}`)
    }
  }, [])

  useEffect(() => { load() }, [load, refreshKey])

  const setAuto = async (auto_export) => {
    setBusy(true)
    try {
      const response = await fetch('/api/drive', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_export }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setStatus(await response.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    const ok = await dialog.confirm({
      title: 'Disconnect Google Drive?',
      message: 'The app will no longer be able to save lectures to your Drive. Files already saved there stay in your Drive.',
      confirmLabel: 'Disconnect',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    try {
      const response = await fetch('/api/drive', { method: 'DELETE' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setStatus(await response.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="settings-section">
      <h3>Google Drive</h3>
      {error && <p className="settings-inline-error">{error}</p>}
      {status && !status.available && (
        <p className="settings-note settings-note-full">
          {isAdmin
            ? 'Not set up yet — add the Google OAuth client under API keys below and users can connect their own Drive.'
            : 'Not available on this server.'}
        </p>
      )}
      {status && status.available && !status.connected && (
        <>
          <p className="settings-note settings-note-full">
            Keep your own copy: each lecture's notes, transcript and MP3 go into an
            "AI Lecture Notes" folder in your Google Drive. The app can only see the files it creates there.
          </p>
          <div className="settings-actions">
            <a className="btn-primary-link" href="/api/drive/connect">
              <DriveIcon size={15} /> Connect Google Drive
            </a>
          </div>
        </>
      )}
      {status && status.connected && (
        <>
          <div className="auth-status tone-ok">
            <span className="auth-icon"><CheckIcon size={13} /></span>
            <div>
              <strong>Connected</strong>
              {status.email && <p className="auth-detail">{status.email}</p>}
              {status.folder_url && (
                <p className="auth-detail">
                  <a href={status.folder_url} target="_blank" rel="noreferrer">Open the "AI Lecture Notes" folder</a>
                </p>
              )}
            </div>
          </div>
          <label className="switch settings-switch">
            <input
              type="checkbox"
              checked={Boolean(status.auto_export)}
              disabled={busy}
              onChange={e => setAuto(e.target.checked)}
            />
            <span className="switch-track" />
            Save each lecture to Drive automatically when the recording stops
          </label>
          <p className="settings-note settings-note-full">
            You can also save any lecture from History → Download → Save to Google Drive. Saving again updates the same files.
          </p>
          <div className="settings-actions">
            <button className="btn-secondary" disabled={busy} onClick={disconnect}>Disconnect</button>
          </div>
        </>
      )}
      {!status && !error && <p className="settings-loading">Loading…</p>}
      {status?.connected === false && status?.available && (
        <p className="settings-note settings-note-full auth-warning-soft">
          <AlertIcon size={13} /> Google shows a consent screen from this app; only the "see and edit files it creates" permission is requested.
        </p>
      )}
    </section>
  )
}

export default DriveSection
