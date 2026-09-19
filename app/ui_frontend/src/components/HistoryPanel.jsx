/**
 * "Your lectures" drawer: past recordings with download, rename, keep (lock),
 * delete-audio and delete actions, plus the storage-quota bar. Opening a row
 * loads that lecture read-only into the workspace. Admins see every user's
 * lectures with an owner tag.
 */
import { useState, useEffect, useCallback } from 'react'
import { HistoryIcon, CloseIcon, TrashIcon, EditIcon, NotesIcon, AudioIcon, AudioOffIcon, DownloadIcon, TranscriptIcon, LockIcon, UnlockIcon, DriveIcon, SpinnerIcon, PdfIcon, DocIcon, UserIcon } from './Icons'
import { useDialog } from './Dialog'
import { prepareMp3, downloadUrl } from '../lib/mp3'
import ShareDialog from './ShareDialog'

const formatMB = bytes => `${Math.round(bytes / 1048576)} MB`

const formatDate = iso => new Date(iso).toLocaleString(undefined, {
  month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
})

const formatDuration = s => {
  if (s < 60) return `${s}s`
  const m = Math.round(s / 60)
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`
}

function HistoryPanel({ user, currentSessionId, onOpen }) {
  const dialog = useDialog()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState(null)
  const [usage, setUsage] = useState(null)
  const retentionDays = usage?.retention_days ?? 14
  const [error, setError] = useState(null)
  const [mp3Busy, setMp3Busy] = useState({}) // session id -> progress label
  const [driveBusy, setDriveBusy] = useState({}) // session id -> step label
  const [drive, setDrive] = useState(null) // /api/drive status for the signed-in user

  const load = useCallback(async () => {
    try {
      const [list, use, drv] = await Promise.all([fetch('/api/sessions'), fetch('/api/sessions/usage'), fetch('/api/drive')])
      if (!list.ok) throw new Error(`HTTP ${list.status}`)
      setItems(await list.json())
      if (use.ok) setUsage(await use.json())
      if (drv.ok) setDrive(await drv.json())
      setError(null)
    } catch (err) {
      setError(`Could not load history: ${err.message}`)
    }
  }, [])

  useEffect(() => { if (open) load() }, [open, load])

  useEffect(() => {
    if (!open) return
    const onKeyDown = e => { if (e.key === 'Escape') setOpen(false) }
    // Close any open download menu when clicking elsewhere.
    const onClick = e => {
      document.querySelectorAll('details.history-download[open]').forEach(d => {
        if (!d.contains(e.target)) d.removeAttribute('open')
      })
    }
    window.addEventListener('keydown', onKeyDown)
    document.addEventListener('click', onClick)
    return () => { window.removeEventListener('keydown', onKeyDown); document.removeEventListener('click', onClick) }
  }, [open])

  const rename = async (item) => {
    const title = await dialog.prompt({ title: 'Rename lecture', label: 'Title', defaultValue: item.title || '', confirmLabel: 'Save' })
    if (title === null) return
    const response = await fetch(`/api/sessions/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    if (response.ok) load()
  }

  // Save notes/transcript/MP3 into the owner's Google Drive; poll until done.
  const saveToDrive = async (item) => {
    if (driveBusy[item.id]) return
    setDriveBusy(b => ({ ...b, [item.id]: 'starting' }))
    try {
      let response = await fetch(`/api/session/${item.id}/drive`, { method: 'POST' })
      let data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      while (data.status === 'running') {
        setDriveBusy(b => ({ ...b, [item.id]: data.step }))
        await new Promise(r => setTimeout(r, 1500))
        response = await fetch(`/api/session/${item.id}/drive/status`)
        data = await response.json()
      }
      if (data.status === 'error') throw new Error(data.error || 'Save failed')
      await load()
      dialog.notice({
        title: 'Saved to Google Drive',
        message: `${Object.keys(data.files).length} file(s) are in your Drive under "AI Lecture Notes".`,
      })
    } catch (err) {
      dialog.notice({ title: 'Could not save to Google Drive', message: err.message })
    } finally {
      setDriveBusy(b => { const n = { ...b }; delete n[item.id]; return n })
    }
  }

  // Share a lecture read-only with other accounts (owner or admin).
  const [sharing, setSharing] = useState(null) // the lecture being shared
  const shareWith = async (usernames) => {
    const response = await fetch(`/api/sessions/${sharing.id}/shares`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ usernames }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
    await load()
  }

  const downloadMp3 = async (item) => {
    if (mp3Busy[item.id]) return
    setMp3Busy(b => ({ ...b, [item.id]: 'Preparing…' }))
    try {
      const { url, filename } = await prepareMp3(item.id, job => {
        setMp3Busy(b => ({ ...b, [item.id]: job.phase === 'converting' ? 'Converting…' : `Preparing ${job.percent ?? 0}%` }))
      })
      downloadUrl(url, filename || `recording-${item.id.slice(0, 8)}.mp3`)
    } catch (err) {
      await dialog.notice({ title: "Couldn't build the MP3", message: err.message })
    } finally {
      setMp3Busy(b => { const n = { ...b }; delete n[item.id]; return n })
    }
  }

  const toggleLock = async (item) => {
    const response = await fetch(`/api/sessions/${item.id}/lock`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locked: !item.locked }),
    })
    if (response.ok) { load(); return }
    const data = await response.json().catch(() => ({}))
    await dialog.notice({ title: "Can't keep this lecture", message: data.detail || `HTTP ${response.status}` })
  }

  const removeAudio = async (item) => {
    const label = item.title || 'this untitled lecture'
    const ok = await dialog.confirm({
      title: 'Delete the audio?',
      message: `The recording for ${label} will be removed permanently and can't be recovered. The transcript and notes stay; the MP3 download goes away.`,
      confirmLabel: 'Delete audio',
      danger: true,
    })
    if (!ok) return
    const response = await fetch(`/api/sessions/${item.id}/audio`, { method: 'DELETE' })
    if (response.ok) load()
  }

  const remove = async (item) => {
    const label = item.title || 'this untitled lecture'
    const ok = await dialog.confirm({
      title: 'Delete this lecture?',
      message: `${label[0].toUpperCase() + label.slice(1)} — its transcript, notes and audio — will be removed permanently. This can't be undone.`,
      confirmLabel: 'Delete lecture',
      danger: true,
    })
    if (!ok) return
    const response = await fetch(`/api/sessions/${item.id}`, { method: 'DELETE' })
    if (response.ok) load()
  }

  const toggle = (
    <button className="btn-icon" onClick={() => setOpen(true)} aria-label="Lecture history" data-tip="Lecture history">
      <HistoryIcon size={18} />
    </button>
  )

  if (!open) return toggle

  return (
    <>
      {toggle}
      <div className="settings-backdrop" onClick={() => setOpen(false)}>
        <div className="settings-panel history-panel" role="dialog" aria-label="Lecture history" onClick={e => e.stopPropagation()}>
          <div className="settings-header">
            <h2>Your lectures</h2>
            <button className="btn-icon settings-close" onClick={() => setOpen(false)} aria-label="Close" data-tip="Close">
              <CloseIcon size={18} />
            </button>
          </div>

          {error && <div className="settings-error">{error}</div>}
          {!items && !error && <p className="settings-loading">Loading…</p>}

          {usage && (
            <div className={`usage-bar${usage.quota_bytes && usage.used_bytes >= usage.quota_bytes ? ' full' : ''}`}>
              <div className="usage-label">
                <span>
                  Audio storage
                  {usage.lock_limit > 0
                    ? <span className="usage-kept"> · Kept: {usage.locked_count} of {usage.lock_limit}</span>
                    : usage.locked_count > 0 && <span className="usage-kept"> · Kept: {usage.locked_count}</span>}
                </span>
                <span>
                  {formatMB(usage.used_bytes)}
                  {usage.quota_bytes ? ` of ${formatMB(usage.quota_bytes)}` : ' (no limit)'}
                </span>
              </div>
              {usage.quota_bytes > 0 && (
                <div className="usage-track">
                  <div className="usage-fill" style={{ width: `${Math.min(100, (usage.used_bytes / usage.quota_bytes) * 100)}%` }} />
                </div>
              )}
            </div>
          )}

          {items && items.length === 0 && (
            <div className="empty-state history-empty">
              <strong>No lectures yet</strong>
              <p>Recordings with a transcript show up here.</p>
            </div>
          )}

          {items && items.length > 0 && (
            <ul className="history-list">
              {items.map(item => (
                <li key={item.id} className={`history-row${item.id === currentSessionId ? ' current' : ''}`}>
                  <button className="history-open" onClick={() => { onOpen(item); setOpen(false) }}>
                    <span className="history-title">{item.title || 'Untitled lecture'}</span>
                    <span className="history-meta">
                      {formatDate(item.created_at)}
                      {' · '}{formatDuration(item.duration_seconds)}
                      {item.notes_version > 0 && <span className="history-tag"><NotesIcon size={12} /> notes</span>}
                      {item.has_audio && <span className="history-tag"><AudioIcon size={12} /> audio</span>}
                      {item.locked && <span className="history-tag history-tag-kept"><LockIcon size={12} /> kept</span>}
                      {driveBusy[item.id]
                        ? <span className="history-tag history-tag-busy"><SpinnerIcon size={12} /> Saving to Drive: {driveBusy[item.id]}</span>
                        : item.drive_saved_at && <span className="history-tag" data-tip={`Saved to Google Drive ${formatDate(item.drive_saved_at)}`}><DriveIcon size={12} /> Drive</span>}
                      {user.is_admin && item.owner && <span className="history-tag history-owner">{item.owner}</span>}
                      {item.shared_by && <span className="history-tag" data-tip="Shared with you — read-only"><UserIcon size={12} /> shared by {item.shared_by}</span>}
                      {item.can_edit && item.shared_with?.length > 0 && <span className="history-tag" data-tip={`Shared with ${item.shared_with.join(', ')}`}><UserIcon size={12} /> shared</span>}
                    </span>
                  </button>
                  <span className="user-row-actions">
                    <details className="history-download">
                      <summary className="btn-icon" data-tip="Download" aria-label={`Download ${item.title || 'lecture'}`}>
                        <DownloadIcon size={16} />
                      </summary>
                      <div className="history-download-menu">
                        <a href={`/api/session/${item.id}/export/transcript.txt`} download={`transcript-${item.id.slice(0, 8)}.txt`}>
                          <TranscriptIcon size={14} /> Transcript
                        </a>
                        {item.notes_version > 0 ? (
                          <a href={`/api/session/${item.id}/export/notes.md`} download={`notes-${item.id.slice(0, 8)}.md`}>
                            <NotesIcon size={14} /> Notes
                          </a>
                        ) : (
                          <span className="disabled"><NotesIcon size={14} /> Notes (none)</span>
                        )}
                        <a href={`/api/session/${item.id}/export/lecture.pdf`} download={`lecture-${item.id.slice(0, 8)}.pdf`}>
                          <PdfIcon size={14} /> PDF (notes + Q&amp;A + transcript)
                        </a>
                        <a href={`/api/session/${item.id}/export/lecture.docx`} download={`lecture-${item.id.slice(0, 8)}.docx`}>
                          <DocIcon size={14} /> Word
                        </a>
                        {item.has_audio ? (
                          <a href={`/api/session/${item.id}/export/audio.mp3`} onClick={e => { e.preventDefault(); downloadMp3(item) }}>
                            <AudioIcon size={14} /> {mp3Busy[item.id] || 'MP3'}
                          </a>
                        ) : (
                          <span className="disabled"><AudioIcon size={14} /> MP3 (audio deleted)</span>
                        )}
                        {drive?.available && !user.is_demo && (drive.connected || user.is_admin) && (
                          driveBusy[item.id]
                            ? <span className="disabled history-menu-divider"><SpinnerIcon size={14} /> Saving to Drive…</span>
                            : (
                              <a href="#drive" className="history-menu-divider" onClick={e => { e.preventDefault(); e.currentTarget.closest('details').removeAttribute('open'); saveToDrive(item) }}>
                                <DriveIcon size={14} /> {item.drive_saved_at ? 'Update in Google Drive' : 'Save to Google Drive'}
                              </a>
                            )
                        )}
                      </div>
                    </details>
                    {!user.is_demo && item.can_edit && (<>
                    <button className={`btn-icon${item.shared_with?.length ? ' btn-icon-active' : ''}`} onClick={() => setSharing(item)} data-tip={item.shared_with?.length ? `Shared with ${item.shared_with.join(', ')} — click to change` : 'Share read-only with other accounts'} aria-label="Share lecture"><UserIcon size={16} /></button>
                    <button className="btn-icon" onClick={() => rename(item)} data-tip="Rename" aria-label="Rename lecture"><EditIcon size={16} /></button>
                    <button
                      className={`btn-icon${item.locked ? ' btn-icon-active' : ''}`}
                      onClick={() => toggleLock(item)}
                      data-tip={item.locked ? `Unlock (allow deletion and ${retentionDays}-day cleanup)` : `Keep (protect from deletion and ${retentionDays}-day cleanup)`}
                      aria-label={item.locked ? 'Unlock lecture' : 'Keep lecture'}
                    >
                      {item.locked ? <LockIcon size={16} /> : <UnlockIcon size={16} />}
                    </button>
                    {item.has_audio && (
                      <button className="btn-icon btn-icon-danger" onClick={() => removeAudio(item)} disabled={item.locked} data-tip={item.locked ? 'Kept — unlock first' : 'Delete audio only (keeps transcript and notes)'} aria-label="Delete audio"><AudioOffIcon size={16} /></button>
                    )}
                    <button className="btn-icon btn-icon-danger" onClick={() => remove(item)} disabled={item.locked} data-tip={item.locked ? 'Kept — unlock first' : 'Delete lecture'} aria-label="Delete lecture"><TrashIcon size={16} /></button>
                    </>)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {sharing && (
            <ShareDialog lecture={sharing} onSave={shareWith} onClose={() => setSharing(null)} />
          )}

          <p className="settings-note settings-note-full history-note">
            {user.is_admin
              ? 'This view includes every lecture on the system. '
              : user.is_demo
                ? 'This is the demo account: these are sample lectures anyone trying the demo can open. '
                : 'This view includes the lectures you have recorded. '}
            Transcripts and notes are retained indefinitely. Audio recordings are removed automatically
            after {retentionDays} days and count toward the storage shown above. To preserve a recording, download the
            MP3 or mark the lecture as kept — kept lectures are excluded from the cleanup and cannot be
            deleted until unlocked.
          </p>
        </div>
      </div>
    </>
  )
}

export default HistoryPanel
