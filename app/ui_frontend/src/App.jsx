/**
 * Root of the UI.
 *
 * `App` gates everything behind sign-in (and handles the emailed reset-password
 * link); `Workspace` is the recording screen: app bar, toolbar, and the three
 * panes (transcript, notes, uploads + chat). Audio is captured with
 * MediaRecorder in 5-second chunks and streamed to the backend over a
 * WebSocket (see hooks/useWebSocket.js); transcript and notes updates come
 * back on the same socket.
 */
import { useState, useCallback, useRef, useEffect } from 'react'
import { v4 as uuidv4 } from 'uuid'
import RecordingControls from './components/RecordingControls'
import TranscriptPane from './components/TranscriptPane'
import NotesPane from './components/NotesPane'
import SessionInfo from './components/SessionInfo'
import ChatPane from './components/ChatPane'
import FileUpload from './components/FileUpload'
import SettingsPanel from './components/SettingsPanel'
import Login from './components/Login'
import ResetPassword from './components/ResetPassword'
import HistoryPanel from './components/HistoryPanel'
import { MicIcon, LogoutIcon, PlusIcon, HelpIcon } from './components/Icons'
import useAuth from './hooks/useAuth'
import { prepareMp3, downloadUrl } from './lib/mp3'
import { useDialog } from './components/Dialog'
import LectureDetailsDialog from './components/LectureDetailsDialog'
import useWebSocket from './hooks/useWebSocket'
import './App.css'

// Screen/tab capture is desktop-only; phones have no getDisplayMedia.
const canCaptureTab = typeof navigator.mediaDevices?.getDisplayMedia === 'function'

function Workspace({ user, onLogout, onUserChange }) {
  const dialog = useDialog()
  const [sessionId, setSessionId] = useState(() => uuidv4())
  // Opened from history: transcript/notes/chat/exports work, recording is off.
  const [viewingPast, setViewingPast] = useState(false)
  const [title, setTitle] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState([])
  const [notes, setNotes] = useState('')
  const [notesVersion, setNotesVersion] = useState(0)
  const [status, setStatus] = useState('Ready')
  const [saveStorage, setSaveStorage] = useState(false)
  const [micMuted, setMicMuted] = useState(false)
  // Names/terms the user typed for this lecture; sent to the server, which
  // feeds them to Whisper as spelling hints. Editable before or during recording.
  const [vocabulary, setVocabulary] = useState('')
  const [notesFocus, setNotesFocus] = useState('')
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const isPausedRef = useRef(false)
  // Screen Wake Lock: phones suspend the page when the screen sleeps, which
  // kills the recorder mid-lecture. Held while recording, re-acquired when the
  // tab becomes visible again (the OS releases it on every hide).
  const wakeLockRef = useRef(null)
  const acquireWakeLock = useCallback(async () => {
    if (!('wakeLock' in navigator) || wakeLockRef.current) return
    try {
      wakeLockRef.current = await navigator.wakeLock.request('screen')
      wakeLockRef.current.addEventListener('release', () => { wakeLockRef.current = null })
    } catch (_) { /* denied (low battery, not visible) — nothing to do */ }
  }, [])
  const releaseWakeLock = useCallback(() => {
    wakeLockRef.current?.release().catch(() => {})
    wakeLockRef.current = null
  }, [])
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && isRecordingRef.current) acquireWakeLock()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [acquireWakeLock])
  const [audioDevices, setAudioDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [captureTabAudio, setCaptureTabAudio] = useState(false)
  const tabAudioActiveRef = useRef(false)
  const isConnectedRef = useRef(false)

  const mediaRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const audioContextRef = useRef(null)
  const micTrackRef = useRef(null)

  // Device list. We never request the microphone on page load: in an installed
  // (home-screen) app that prompt fires during launch and is often auto-dismissed,
  // after which the app is treated as denied. Permission is requested on a tap —
  // Start recording or the "Enable microphone" button — and labels fill in then.
  const [micState, setMicState] = useState('unknown') // 'unknown' | 'granted' | 'denied'
  // True after ~15 s of digital silence while recording (mic held by a call, etc.).
  const [noAudio, setNoAudio] = useState(false)
  const meterRef = useRef(null) // { ctx, timer }
  const isInstalledApp = window.matchMedia?.('(display-mode: standalone)').matches

  const loadDevices = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      // Without permission, browsers list inputs with empty ids; keep only usable ones.
      const inputs = devices.filter(d => d.kind === 'audioinput' && d.deviceId)
      setAudioDevices(inputs)
      setSelectedDeviceId(prev => (prev && inputs.some(d => d.deviceId === prev)) ? prev : (inputs[0]?.deviceId || ''))
      if (inputs.some(d => d.label)) setMicState('granted')
    } catch (_) {}
  }, [])

  // Back from the Google Drive consent page (/api/drive/callback redirects here),
  // or from the email-confirmation link (/api/auth/verify).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const drive = params.get('drive')
    const verified = params.get('verified')
    const approved = params.get('approved')
    if (!drive && !verified && !approved) return
    window.history.replaceState({}, '', window.location.pathname)
    if (verified) {
      dialog.notice(verified === '1'
        ? { title: 'Email confirmed', message: 'Your account is ready! — Welcome to AI Lecture Notes.' }
        : verified === 'pending'
          ? { title: 'Email confirmed', message: 'Thanks — your account now needs to be approved by an administrator. You will get an email as soon as it is active.' }
          : { title: 'Link expired', message: 'That confirmation link is no longer valid. Sign in and use "Send the link again" to get a fresh one.' })
      return
    }
    if (approved) {
      const who = params.get('user') || 'The account'
      dialog.notice(approved === '1'
        ? { title: 'Account approved', message: `${who} can sign in now and has been emailed.` }
        : approved === 'already'
          ? { title: 'Already approved', message: `${who} was approved earlier — nothing to do.` }
          : { title: 'Link expired', message: 'That approval link is no longer valid. You can approve the account under Settings → Users.' })
      return
    }
    if (drive === 'connected') {
      dialog.notice({
        title: 'Google Drive connected',
        message: 'Finished lectures will be saved to an "AI Lecture Notes" folder in your Drive. You can turn automatic saving off in Settings → Google Drive.',
      })
    } else {
      const reason = params.get('reason')
      dialog.notice({
        title: 'Google Drive was not connected',
        message: reason === 'expired'
          ? 'The sign-in took too long — please try again from Settings.'
          : reason === 'access_denied' || reason === 'cancelled'
            ? 'The Google sign-in was cancelled.'
            : 'Google did not complete the connection. Try again from Settings → Google Drive.',
      })
    }
  }, [dialog])

  useEffect(() => {
    loadDevices()
    navigator.mediaDevices?.addEventListener('devicechange', loadDevices)
    // Reflect an existing decision without prompting (not supported everywhere).
    let status
    navigator.permissions?.query({ name: 'microphone' }).then(p => {
      status = p
      const apply = () => setMicState(p.state === 'granted' ? 'granted' : p.state === 'denied' ? 'denied' : 'unknown')
      apply()
      p.onchange = apply
    }).catch(() => {})
    return () => {
      navigator.mediaDevices?.removeEventListener('devicechange', loadDevices)
      if (status) status.onchange = null
    }
  }, [loadDevices])

  const micErrorMessage = useCallback((error) => {
    if (!window.isSecureContext) return 'Error: Microphone needs HTTPS (or localhost) — open the site over https://'
    switch (error?.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return isInstalledApp
          ? 'Microphone is blocked for this app. Android: long-press the app icon → App info → Permissions → Microphone → Allow. iPhone: Settings → Lecture Notes → Microphone.'
          : 'Microphone is blocked for this site. Tap the icon next to the address bar → Permissions → Microphone → Allow, then try again.'
      case 'NotFoundError':
        return 'No microphone found on this device.'
      case 'NotReadableError':
        return 'The microphone is in use by another app. Close it and try again.'
      default:
        return 'Error: Could not access audio device'
    }
  }, [isInstalledApp])

  // Level meter: the OS hands other apps a muted stream during phone/VoIP calls,
  // and the recorder happily records the silence. Sample the stream every
  // second and warn after 15 s of digital silence so the user finds out now,
  // not after the lecture.
  const SILENCE_SECONDS = 15
  const stopLevelMeter = useCallback(() => {
    const m = meterRef.current
    if (!m) return
    clearInterval(m.timer)
    m.ctx.close().catch(() => {})
    meterRef.current = null
    setNoAudio(false)
  }, [])

  const startLevelMeter = useCallback((stream) => {
    stopLevelMeter()
    try {
      const ctx = new AudioContext()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 2048
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Float32Array(analyser.fftSize)
      let silentFor = 0
      const timer = setInterval(() => {
        analyser.getFloatTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
        const rms = Math.sqrt(sum / buf.length)
        // Ignore while the user has muted the mic on purpose.
        if (isPausedRef.current || (micTrackRef.current && !micTrackRef.current.enabled && !tabAudioActiveRef.current)) { silentFor = 0; setNoAudio(false); return }
        silentFor = rms < 0.0005 ? silentFor + 1 : 0
        setNoAudio(silentFor >= SILENCE_SECONDS)
      }, 1000)
      meterRef.current = { ctx, timer }
    } catch (_) {
      // No Web Audio: recording still works, just without the warning.
    }
  }, [stopLevelMeter])

  // Explicit permission request from a tap, so the prompt is reliable everywhere.
  const enableMicrophone = useCallback(async () => {
    try {
      const temp = await navigator.mediaDevices.getUserMedia({ audio: true })
      temp.getTracks().forEach(t => t.stop())
      setMicState('granted')
      await loadDevices()
      setStatus('Microphone ready')
    } catch (error) {
      setMicState(error?.name === 'NotAllowedError' ? 'denied' : micState)
      setStatus(micErrorMessage(error))
    }
  }, [loadDevices, micErrorMessage, micState])

  const handleMessage = useCallback((message) => {
    if (message.type === 'transcript_delta') {
      const entry = {
        id: message.segment_id,
        text: message.text,
        chunk: message.chunk,
        tsStart: message.ts_start,
        tsEnd: message.ts_end,
      }
      // Chunks are transcribed concurrently, so a later chunk can finish first.
      // Insert by (chunk, tsStart) rather than appending in arrival order.
      setTranscript(prev => {
        let i = prev.length
        while (i > 0) {
          const p = prev[i - 1]
          if (p.chunk < entry.chunk) break
          if (p.chunk === entry.chunk && p.tsStart <= entry.tsStart) break
          i--
        }
        if (i === prev.length) return [...prev, entry]
        return [...prev.slice(0, i), entry, ...prev.slice(i)]
      })
    } else if (message.type === 'notes_update') {
      setNotes(message.notes_md)
      setNotesVersion(message.version)
    } else if (message.type === 'status') {
      setStatus(message.message)
    } else if (message.type === 'quota_exceeded') {
      // stop=true: refused at start, so tear down the recorder we just started.
      if (message.stop) stopRecordingRef.current?.()
      setStatus(message.message)
      dialog.notice({ title: 'Storage quota reached', message: message.message })
    }
  }, [])

  const stopRecordingRef = useRef(null)
  // After a reconnect mid-recording, re-send the options the server keeps in
  // memory (they are dropped when the socket closes or the server restarts).
  const isRecordingRef = useRef(false)
  const saveStorageRef = useRef(false)
  const sendMessageRef = useRef(null)
  const onReconnect = useCallback(() => {
    if (isRecordingRef.current) {
      sendMessageRef.current?.({ type: 'resume', save_storage: saveStorageRef.current }, true)
    }
  }, [])
  const { sendMessage, sendBinary, isConnected, queuedChunks } = useWebSocket(sessionId, handleMessage, onReconnect)
  isConnectedRef.current = isConnected
  sendMessageRef.current = sendMessage

  const startRecording = useCallback(async () => {
    try {
      const constraints = {
        audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true,
      }
      const micStream = await navigator.mediaDevices.getUserMedia(constraints)
      const micTrack = micStream.getAudioTracks()[0]
      micTrackRef.current = micTrack
      // Apply pre-record mute state immediately
      micTrack.enabled = !micMuted
      tabAudioActiveRef.current = false

      let recordingStream = micStream
      let statusLabel = audioDevices.find(d => d.deviceId === selectedDeviceId)?.label || 'mic'

      if (captureTabAudio) {
        try {
          const tabStream = await navigator.mediaDevices.getDisplayMedia({
            audio: true,
            video: true,
          })
          tabStream.getVideoTracks().forEach(t => t.stop())

          const audioCtx = new AudioContext()
          audioContextRef.current = audioCtx
          const dest = audioCtx.createMediaStreamDestination()
          audioCtx.createMediaStreamSource(micStream).connect(dest)
          audioCtx.createMediaStreamSource(tabStream).connect(dest)

          recordingStream = dest.stream
          streamRef.current = { mic: micStream, tab: tabStream }
          tabAudioActiveRef.current = true
          statusLabel += ' + tab audio'
        } catch (err) {
          console.warn('Tab audio capture cancelled or failed:', err)
          setStatus('Tab audio unavailable, recording mic only')
          recordingStream = micStream
          streamRef.current = micStream
        }
      } else {
        streamRef.current = micStream
      }

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'

      const mediaRecorder = new MediaRecorder(recordingStream, { mimeType })
      mediaRecorderRef.current = mediaRecorder

      mediaRecorder.ondataavailable = (event) => {
        // Every chunk is sent — even while disconnected (the socket hook queues
        // and replays them) and even while the mic is muted. A muted track
        // yields silence, which the server skips before transcription; dropping
        // chunks instead would break the stream: the first chunk carries the
        // WebM header every later chunk needs, and gaps shift the timestamps.
        if (event.data.size > 0) sendBinary(event.data)
      }

      mediaRecorder.start(5000)
      startLevelMeter(recordingStream)
      setIsRecording(true)
      isRecordingRef.current = true
      saveStorageRef.current = saveStorage
      acquireWakeLock()
      if (micState !== 'granted') { setMicState('granted'); loadDevices() }
      sendMessage({ type: 'start', title: title || undefined, save_storage: saveStorage, vocabulary, notes_focus: notesFocus })
      setStatus(`Recording (${statusLabel})${micMuted ? ' — mic muted' : ''}...`)
    } catch (error) {
      console.error('Error starting recording:', error)
      if (error?.name === 'NotAllowedError') setMicState('denied')
      setStatus(micErrorMessage(error))
    }
  }, [sendMessage, sendBinary, title, saveStorage, vocabulary, notesFocus, selectedDeviceId, audioDevices, captureTabAudio, micState, loadDevices, micErrorMessage, startLevelMeter, acquireWakeLock])

  // Mute only disables the mic track: the recorder and the stream keep going,
  // so the transcript resumes the moment the mic is enabled again.
  const toggleMicMute = useCallback(() => {
    setMicMuted(prev => {
      const next = !prev
      if (micTrackRef.current) {
        micTrackRef.current.enabled = !next
      }
      if (isRecordingRef.current) {
        setStatus(next ? 'Recording — mic muted (transcript paused)' : 'Recording — mic on')
      }
      return next
    })
  }, [])

  // Pause freezes the MediaRecorder: no chunks are produced until resume, and
  // the next chunk after resume is a plain continuation, so the server needs
  // nothing special. The lecture stays open — no final notes, no export.
  const pauseRecording = useCallback(() => {
    const rec = mediaRecorderRef.current
    if (!rec || rec.state !== 'recording') return
    rec.pause()
    isPausedRef.current = true
    setIsPaused(true)
    setStatus('Paused — press Resume to keep recording')
  }, [])

  const resumeRecording = useCallback(() => {
    const rec = mediaRecorderRef.current
    if (!rec || rec.state !== 'paused') return
    rec.resume()
    isPausedRef.current = false
    setIsPaused(false)
    setStatus(micMuted ? 'Recording — mic muted (transcript paused)' : 'Recording resumed')
  }, [micMuted])

  const stopRecording = useCallback(() => {
    stopLevelMeter()
    releaseWakeLock()
    isPausedRef.current = false
    setIsPaused(false)
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    if (streamRef.current) {
      if (streamRef.current.mic) {
        streamRef.current.mic.getTracks().forEach(t => t.stop())
        streamRef.current.tab?.getTracks().forEach(t => t.stop())
      } else {
        streamRef.current.getTracks().forEach(t => t.stop())
      }
      streamRef.current = null
    }

    micTrackRef.current = null
    tabAudioActiveRef.current = false
    setMicMuted(false)
    setIsRecording(false)
    isRecordingRef.current = false
    sendMessage({ type: 'stop' })
    setStatus('Processing...')
  }, [sendMessage, stopLevelMeter, releaseWakeLock])

  // Hand the URL straight to the browser's download manager. The server marks
  // every export as an attachment, so this saves the file on every platform —
  // including Android home-screen apps, where a fetched blob: URL could open in
  // the media viewer and loop instead of downloading.
  stopRecordingRef.current = stopRecording

  const triggerDownload = useCallback((url, filename, loadingMsg) => {
    setStatus(loadingMsg)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => setStatus('Download started — check your downloads'), 1500)
  }, [])

  const exportNotes = useCallback(() =>
    triggerDownload(
      `/api/session/${sessionId}/export/notes.md`,
      `notes-${sessionId.slice(0, 8)}.md`,
      'Exporting notes…',
    ), [sessionId, triggerDownload])

  const exportTranscript = useCallback(() =>
    triggerDownload(
      `/api/session/${sessionId}/export/transcript.txt`,
      `transcript-${sessionId.slice(0, 8)}.txt`,
      'Exporting transcript…',
    ), [sessionId, triggerDownload])

  // Formatted document (notes + Q&A + transcript) — PDF or Word.
  const exportPdf = useCallback(() =>
    triggerDownload(
      `/api/session/${sessionId}/export/lecture.pdf`,
      `lecture-${sessionId.slice(0, 8)}.pdf`,
      'Building the PDF…',
    ), [sessionId, triggerDownload])
  const exportDocx = useCallback(() =>
    triggerDownload(
      `/api/session/${sessionId}/export/lecture.docx`,
      `lecture-${sessionId.slice(0, 8)}.docx`,
      'Building the Word file…',
    ), [sessionId, triggerDownload])

  // MP3: build on the server with a visible progress state, then download.
  const [mp3Progress, setMp3Progress] = useState(null) // null | { percent, phase }
  const exportAudio = useCallback(async () => {
    if (mp3Progress) return
    setMp3Progress({ percent: 0, phase: 'fetching' })
    setStatus('Preparing MP3…')
    try {
      const { url, filename } = await prepareMp3(sessionId, job => {
        setMp3Progress({ percent: job.percent ?? 0, phase: job.phase })
        setStatus(job.phase === 'converting' ? 'Converting to MP3…' : `Preparing MP3… ${job.percent ?? 0}%`)
      })
      downloadUrl(url, filename || `recording-${sessionId.slice(0, 8)}.mp3`)
      setStatus('MP3 ready — check your downloads')
    } catch (err) {
      setStatus(`MP3 export failed: ${err.message}`)
    } finally {
      setMp3Progress(null)
    }
  }, [sessionId, mp3Progress])

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        if (streamRef.current.mic) {
          streamRef.current.mic.getTracks().forEach(t => t.stop())
          streamRef.current.tab?.getTracks().forEach(t => t.stop())
        } else {
          streamRef.current.getTracks().forEach(t => t.stop())
        }
      }
      if (audioContextRef.current) audioContextRef.current.close()
    }
  }, [])

  // Which lecture is on screen; lets a slow fetch for one lecture be ignored
  // once the user has moved on (opened another, or started a new one).
  const currentSessionRef = useRef(null)
  currentSessionRef.current = sessionId

  const openPastLecture = useCallback(async (item) => {
    if (isRecording) return
    currentSessionRef.current = item.id
    setSessionId(item.id)
    setViewingPast(true)
    setTitle(item.title || '')
    setVocabulary('')
    setNotesFocus('')
    setTranscript([])
    setNotes('')
    setNotesVersion(0)
    setStatus('Loading lecture…')
    try {
      const [t, n, d] = await Promise.all([
        fetch(`/api/session/${item.id}/transcript`),
        fetch(`/api/session/${item.id}/notes`),
        fetch(`/api/session/${item.id}`),
      ])
      if (d.ok && currentSessionRef.current === item.id) {
        const details = await d.json()
        setVocabulary(details.vocabulary || '')
        setNotesFocus(details.notes_focus || '')
      }
      if (currentSessionRef.current !== item.id) return // user moved on meanwhile
      if (t.ok) {
        const data = await t.json()
        if (data.text) setTranscript([{ id: `${item.id}-full`, text: data.text }])
      }
      if (n.ok) {
        const data = await n.json()
        setNotes(data.notes_md || '')
        setNotesVersion(data.version || 0)
      }
      if (currentSessionRef.current !== item.id) return
      setStatus(`Viewing lecture from ${new Date(item.created_at).toLocaleDateString()}`)
    } catch (err) {
      setStatus(`Could not load lecture: ${err.message}`)
    }
  }, [isRecording])

  // Save the per-lecture hints. PATCH covers every state (before, during and
  // after a recording): the server re-prompts Whisper itself.
  const saveDetails = useCallback(async ({ vocabulary: terms, notes_focus }) => {
    const response = await fetch(`/api/session/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vocabulary: terms, notes_focus }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      dialog.notice({ title: 'Could not save', message: data.detail || `HTTP ${response.status}` })
      return
    }
    setVocabulary(terms)
    setNotesFocus(notes_focus)
  }, [sessionId, dialog])

  const startNewLecture = useCallback(() => {
    if (isRecording) return
    const fresh = uuidv4()
    currentSessionRef.current = fresh
    setSessionId(fresh)
    setViewingPast(false)
    setTitle('')
    setVocabulary('')
    setNotesFocus('')
    setTranscript([])
    setNotes('')
    setNotesVersion(0)
    setStatus('Ready')
  }, [isRecording])

  // What the Mute switch actually silences: the selected input device. With a
  // virtual device (BlackHole, Loopback) that is the meeting audio, not the user.
  const inputLabel = audioDevices.find(d => d.deviceId === selectedDeviceId)?.label || 'microphone'
  const inputIsVirtual = /blackhole|loopback|soundflower|virtual|aggregate/i.test(inputLabel)
  const inputShort = inputIsVirtual
    ? inputLabel.replace(/\s*\(.*?\)\s*/g, '').split(' ').slice(0, 2).join(' ')
    : 'mic'

  return (
    <div className="app">
      <header className="app-bar">
        <div className="brand">
          <img className="brand-mark" src="/logo-mark.svg" alt="M.G. Network and Technology Solutions" />
          <div className="brand-text">
            <h1>AI Lecture Notes</h1>
            <span className="brand-sub">M.G. Network and Technology Solutions</span>
          </div>
        </div>

        <div className="app-bar-divider" />

        <SessionInfo
          sessionId={sessionId}
          title={title}
          onTitleChange={setTitle}
          disabled={isRecording || viewingPast || user.is_demo}
          vocabulary={vocabulary}
          notesFocus={notesFocus}
          onEditDetails={user.is_demo ? undefined : () => setDetailsOpen(true)}
        />

        <div className="app-bar-actions">
          <span className="user-name" data-tip={user.is_admin ? 'Signed in as an administrator' : 'Signed in'}>{user.username}</span>
          <span
            className={`status-pill ${isConnected ? 'connected' : 'disconnected'}`}
            data-tip={isConnected
              ? (queuedChunks ? `Reconnected — sending ${queuedChunks * 5} s of buffered audio` : 'Live link to the server is up')
              : (isRecording
                ? `Not connected — recording continues, ${queuedChunks * 5} s buffered and will be sent when the link is back`
                : 'Not connected to the server')}
          >
            <span className="status-dot" />
            <span className="status-label">{isConnected ? 'Connected' : (isRecording && queuedChunks ? `Buffering ${queuedChunks * 5}s` : 'Disconnected')}</span>
          </span>
          <HistoryPanel user={user} currentSessionId={sessionId} onOpen={openPastLecture} />
          <SettingsPanel user={user} onUserChange={onUserChange} onLogout={onLogout} />
          <a className="btn-icon" href="/guide" target="_blank" rel="noreferrer" aria-label="User guide" data-tip="User guide (opens in a new tab)">
            <HelpIcon size={18} />
          </a>
          <span className="user-menu">
            <button className="btn-icon" onClick={onLogout} aria-label="Sign out" data-tip="Sign out">
              <LogoutIcon size={18} />
            </button>
          </span>
        </div>
      </header>

      {user.is_demo && (
        <div className="demo-banner">
          You're in the <strong>demo</strong> — a read-only account. Open a lecture from History, read the transcript and notes, ask questions, download exports.
          Recording, uploads and settings changes are off. <a href="/" onClick={e => { e.preventDefault(); onLogout() }}>Sign out</a> to create your own account.
        </div>
      )}

      {detailsOpen && (
        <LectureDetailsDialog
          vocabulary={vocabulary}
          notesFocus={notesFocus}
          onSave={saveDetails}
          onClose={() => setDetailsOpen(false)}
        />
      )}

      <div className="toolbar">
        {viewingPast && (
          <button className="btn-primary btn-new-lecture" onClick={startNewLecture} data-tip="Leave this past lecture and start a fresh recording">
            <PlusIcon size={16} />
            New lecture
          </button>
        )}
        <RecordingControls
          readOnly={viewingPast || user.is_demo}
          isRecording={isRecording}
          isPaused={isPaused}
          onStart={startRecording}
          onStop={stopRecording}
          onPause={pauseRecording}
          onResume={resumeRecording}
          onExport={exportNotes}
          onExportTranscript={exportTranscript}
          onExportPdf={exportPdf}
          onExportDocx={exportDocx}
          onExportAudio={exportAudio}
          mp3Progress={mp3Progress}
          hasNotes={notesVersion > 0}
          hasTranscript={transcript.length > 0}
          isConnected={isConnected}
        />
        <span className="status-text">{status}</span>

        <div className="toolbar-spacer" />

        {!viewingPast && !user.is_demo && (<>
        <label className="device-select-label" data-tip="Which microphone to record from">
          <MicIcon />
          <span className="visually-hidden">Audio input</span>
          {micState === 'granted' && audioDevices.length > 0 ? (
            <select
              className="device-select"
              value={selectedDeviceId}
              onChange={e => setSelectedDeviceId(e.target.value)}
              disabled={isRecording}
            >
              {audioDevices.map(d => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || `Microphone (${d.deviceId.slice(0, 8)})`}
                </option>
              ))}
            </select>
          ) : (
            <button type="button" className="btn-secondary" onClick={enableMicrophone} disabled={isRecording}
              data-tip={micState === 'denied' ? 'Show how to unblock the microphone' : 'Ask for microphone access so the device list can load'}>
              {micState === 'denied' ? 'Microphone blocked — how to fix' : 'Enable microphone'}
            </button>
          )}
        </label>

        <div className="toolbar-switches">
          {canCaptureTab && (
            <label className="switch" data-tip="Also record audio from a browser tab (e.g. a Zoom window) alongside the mic">
              <input
                type="checkbox"
                checked={captureTabAudio}
                onChange={e => setCaptureTabAudio(e.target.checked)}
                disabled={isRecording}
              />
              <span className="switch-track" />
              Tab audio
            </label>
          )}
          <label
            className="switch"
            data-tip={inputIsVirtual
              ? `Silences ${inputShort} — the meeting audio, not you. The recording keeps running. To mute yourself in the call, use Zoom's mute button.`
              : `Silences your microphone; the recording keeps running and the transcript resumes when you unmute${captureTabAudio ? ' (tab audio is unaffected)' : ''}.`}
          >
            <input type="checkbox" checked={micMuted} onChange={toggleMicMute} />
            <span className="switch-track" />
            Mute {inputShort}
          </label>
          <label className="switch" data-tip="Transcribe without keeping the recording — no MP3 later, no storage used">
            <input
              type="checkbox"
              checked={saveStorage}
              onChange={e => setSaveStorage(e.target.checked)}
              disabled={isRecording}
            />
            <span className="switch-track" />
            Don't keep audio
          </label>
        </div>
        </>)}
      </div>

      {viewingPast && (
        <p className="toolbar-hint toolbar-hint-info">
          Viewing a past lecture — you can read, export, and ask questions about it. Recording is off; use New lecture to record.
        </p>
      )}

      {!isRecording && !viewingPast && (
        <p className="toolbar-hint toolbar-hint-phone">
          Recording a call on this phone? Put it on speakerphone — phones only let apps hear your side of a call, so the other party is picked up through the speaker.
        </p>
      )}

      {noAudio && isRecording && (
        <p className="toolbar-hint toolbar-hint-danger">
          No audio is reaching the recorder. If you're on a phone or Zoom call, the call has the microphone — phones don't let another app hear a call. Record from a different device, or on a computer use Tab audio to capture the call.
        </p>
      )}

      {captureTabAudio && !isRecording && (
        <p className="toolbar-hint">
          Tab audio: pick "Chrome Tab" in the share dialog and check "Share tab audio".
        </p>
      )}

      <main className="main-content">
        <TranscriptPane transcript={transcript} />
        <NotesPane
          notes={notes}
          version={notesVersion}
          sessionId={sessionId}
          isRecording={isRecording}
          readOnly={user.is_demo}
          onNotesChange={(md, v) => { setNotes(md); setNotesVersion(v) }}
        />
        <div className="right-pane">
          {/* Keyed so uploads and chat history reset when switching lectures. */}
          {!user.is_demo && <FileUpload key={`upload-${sessionId}`} sessionId={sessionId} />}
          <ChatPane key={`chat-${sessionId}`} sessionId={sessionId} readOnly={user.is_demo} />
        </div>
      </main>
    </div>
  )
}

// The workspace only mounts once signed in, so its websocket never connects
// without a login cookie.
// The emailed reset link lands on /reset-password?token=…; everything else is
// the single-page app at /.
const resetToken = window.location.pathname === '/reset-password'
  ? new URLSearchParams(window.location.search).get('token')
  : null

function App() {
  const { user, login, register, demo, logout, refresh } = useAuth()
  if (resetToken) {
    return <ResetPassword token={resetToken} onDone={() => { window.history.replaceState(null, '', '/'); window.location.reload() }} />
  }
  if (user === undefined) return null
  if (user === null) return <Login onLogin={login} onRegister={register} onDemo={demo} />
  return <Workspace user={user} onLogout={logout} onUserChange={refresh} />
}

export default App
