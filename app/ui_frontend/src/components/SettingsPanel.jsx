/**
 * Settings dialog. Everyone gets Appearance and "Your account"; admins also
 * get API keys, provider/model choice, limits, sign-up control, and user
 * management. Backend settings load lazily and only for admins; the form
 * keeps a local draft and PUTs just the changed fields.
 */
import { useState, useEffect, useCallback } from 'react'
import useTheme from '../hooks/useTheme'
import { GearIcon, CloseIcon, CheckIcon, AlertIcon, KeyIcon, MonitorIcon, SunIcon, MoonIcon } from './Icons'
import UsersSection from './UsersSection'
import PasswordSection from './PasswordSection'
import DriveSection from './DriveSection'

const VISION_MODELS = [
  { id: 'claude-opus-5', label: 'Claude Opus 5 — best at dense slides' },
  { id: 'claude-sonnet-5', label: 'Claude Sonnet 5 — balanced' },
  { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5 — cheapest, weakest on slides' },
]

const WHISPER_MODELS = [
  { id: 'tiny', label: 'tiny — fastest, least accurate' },
  { id: 'base', label: 'base' },
  { id: 'small', label: 'small — keeps up with realtime on CPU' },
  { id: 'medium', label: 'medium — slower than realtime on CPU' },
  { id: 'large-v3', label: 'large-v3 — GPU or offline reruns only' },
]

const AUTH_LABELS = {
  api_key: { icon: <KeyIcon size={13} />, tone: 'ok', text: 'API key' },
  auth_token: { icon: <KeyIcon size={13} />, tone: 'ok', text: 'OAuth token' },
  profile: { icon: <CheckIcon size={13} />, tone: 'ok', text: 'Claude login' },
  misconfigured: { icon: <AlertIcon size={13} />, tone: 'warn', text: 'Misconfigured' },
  none: { icon: <AlertIcon size={13} />, tone: 'neutral', text: 'No credentials' },
}

const THEME_OPTIONS = [
  { id: 'system', label: 'System', icon: <MonitorIcon size={22} /> },
  { id: 'light', label: 'Light', icon: <SunIcon size={22} /> },
  { id: 'dark', label: 'Dark', icon: <MoonIcon size={22} /> },
]

function ProviderKey({ label, keyMasked, keyInput, onKeyInput, onSaveKey, onClearKey, test, onTest, saving, help }) {
  return (
    <>
      <label className="settings-field">
        <span>{label} API key</span>
        <input
          type="password"
          placeholder={keyMasked ? `Saved (${keyMasked}) — paste to replace` : 'Paste key…'}
          value={keyInput}
          onChange={e => onKeyInput(e.target.value)}
          autoComplete="off"
        />
      </label>
      <p className="settings-note">{help}</p>
      <div className="settings-actions">
        <button disabled={saving || !keyInput.trim()} onClick={onSaveKey}>Save {label} key</button>
        {keyMasked && <button className="btn-secondary" disabled={saving} onClick={onClearKey}>Clear key</button>}
        {keyMasked && <button className="btn-secondary" disabled={saving || test?.pending} onClick={onTest}>{test?.pending ? 'Testing…' : 'Test connection'}</button>}
      </div>
      {test && !test.pending && (
        <p className={test.ok ? 'settings-inline-ok' : 'settings-inline-error'}>{test.detail}</p>
      )}
    </>
  )
}

function SettingsPanel({ user, onUserChange }) {
  const isAdmin = user?.is_admin
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState(null)
  const [draft, setDraft] = useState({})
  const [keyInput, setKeyInput] = useState('')
  const [providerKeys, setProviderKeys] = useState({ gemini: '', openai: '' })
  const [googleClient, setGoogleClient] = useState({ id: '', secret: '' })
  const [providerTest, setProviderTest] = useState({})
  const [geminiModels, setGeminiModels] = useState(null) // null = not loaded, [] = failed
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const { theme, setTheme } = useTheme()

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/settings')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      setSettings(data)
      setDraft({
        vision_model: data.vision_model,
        ollama_model: data.ollama_model,
        text_provider: data.text_provider,
        vision_provider: data.vision_provider,
        claude_text_model: data.claude_text_model,
        gemini_model: data.gemini_model,
        openai_model: data.openai_model,
        whisper_model: data.whisper_model,
        notes_interval_seconds: data.notes_interval_seconds,
        storage_quota_mb: data.storage_quota_mb,
        audio_retention_days: data.audio_retention_days,
        registration_open: data.registration_open,
        max_locked_lectures: data.max_locked_lectures,
      })
      setError(null)
    } catch (err) {
      setError(`Could not load settings: ${err.message}`)
    }
  }, [])

  useEffect(() => { if (open && isAdmin && !settings) load() }, [open, isAdmin, settings, load])

  // Esc closes the dialog, matching the backdrop click.
  useEffect(() => {
    if (!open) return
    const onKeyDown = e => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  const save = async (payload, successMessage) => {
    setSaving(true)
    setMessage(null)
    setError(null)
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      setSettings(data)
      setDraft({
        vision_model: data.vision_model,
        ollama_model: data.ollama_model,
        text_provider: data.text_provider,
        vision_provider: data.vision_provider,
        claude_text_model: data.claude_text_model,
        gemini_model: data.gemini_model,
        openai_model: data.openai_model,
        whisper_model: data.whisper_model,
        notes_interval_seconds: data.notes_interval_seconds,
        storage_quota_mb: data.storage_quota_mb,
        audio_retention_days: data.audio_retention_days,
        registration_open: data.registration_open,
        max_locked_lectures: data.max_locked_lectures,
      })
      setMessage(
        data.restart_required.length
          ? `${successMessage} — ${data.restart_required.join(', ')} takes effect after a backend restart.`
          : successMessage,
      )
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setSaving(false)
    }
  }

  const loadGeminiModels = useCallback(async () => {
    try {
      const response = await fetch('/api/settings/gemini-models')
      setGeminiModels(response.ok ? await response.json() : [])
    } catch {
      setGeminiModels([])
    }
  }, [])

  useEffect(() => {
    if (open && settings?.gemini_key_masked) loadGeminiModels()
  }, [open, settings?.gemini_key_masked, loadGeminiModels])

  const testProvider = async (name) => {
    setProviderTest(t => ({ ...t, [name]: { pending: true } }))
    try {
      const response = await fetch(`/api/settings/test-provider/${name}`, { method: 'POST' })
      const data = await response.json()
      setProviderTest(t => ({ ...t, [name]: data }))
    } catch (err) {
      setProviderTest(t => ({ ...t, [name]: { ok: false, detail: err.message } }))
    }
  }

  const dirty = settings && Object.keys(draft).some(k => draft[k] !== settings[k])

  const auth = settings?.auth
  const authLabel = auth ? (AUTH_LABELS[auth.source] || AUTH_LABELS.none) : null

  const toggle = (
    <button className="btn-icon settings-toggle" onClick={() => setOpen(true)} aria-label="Settings" data-tip="Settings">
      <GearIcon size={18} />
    </button>
  )

  if (!open) return toggle

  return (
    <>
      {toggle}
      <div className="settings-backdrop" onClick={() => setOpen(false)}>
      {/* Stop clicks inside the dialog from reaching the backdrop. */}
      <div className="settings-panel" role="dialog" aria-label="Settings" onClick={e => e.stopPropagation()}>
      <div className="settings-header">
        <h2>Settings</h2>
        <button className="btn-icon settings-close" onClick={() => setOpen(false)} aria-label="Close" data-tip="Close">
          <CloseIcon size={18} />
        </button>
      </div>

      {/* Appearance is browser-local, so it renders even if the backend settings failed to load. */}
      <section className="settings-section">
        <h3>Appearance</h3>
        <p className="settings-note settings-note-full">
          Saved in this browser. System follows your operating system setting.
        </p>
        <div className="theme-picker" role="radiogroup" aria-label="Theme">
          {THEME_OPTIONS.map(opt => (
            <button
              key={opt.id}
              role="radio"
              aria-checked={theme === opt.id}
              className={`theme-option${theme === opt.id ? ' selected' : ''}`}
              onClick={() => setTheme(opt.id)}
            >
              {opt.icon}
              {opt.label}
            </button>
          ))}
        </div>
      </section>

      <PasswordSection user={user} onUserChange={onUserChange} />

      {/* Admins get this right after the OAuth client fields (inside the admin block below). */}
      {!isAdmin && <DriveSection isAdmin={false} />}

      {error && <div className="settings-error">{error}</div>}
      {message && <div className="settings-message">{message}</div>}
      {isAdmin && !settings && !error && <p className="settings-loading">Loading…</p>}

      {settings && (
        <>
          <section className="settings-section">
            <h3>API keys</h3>
            <p className="settings-note settings-note-full">Save any keys you have; choose which provider does what under Models below.</p>
            <h4 className="settings-subheading">Claude (Anthropic)</h4>
            <div className={`auth-status tone-${authLabel.tone}`}>
              <span className="auth-icon">{authLabel.icon}</span>
              <div>
                <strong>{authLabel.text}</strong>
                {auth.key_masked && <code className="auth-key">{auth.key_masked}</code>}
                <p className="auth-detail">{auth.detail}</p>
              </div>
            </div>

            {auth.warnings.map((w, i) => (
              <p key={i} className="auth-warning"><AlertIcon size={14} /> {w}</p>
            ))}

            <label className="settings-field">
              <span>API key</span>
              <input
                type="password"
                placeholder={auth.key_masked ? 'Replace stored key…' : 'sk-ant-…'}
                value={keyInput}
                onChange={e => setKeyInput(e.target.value)}
                autoComplete="off"
              />
            </label>
            <div className="settings-actions">
              <button
                disabled={saving || !keyInput.trim()}
                onClick={async () => {
                  // Keep what was typed if the save failed.
                  if (await save({ anthropic_api_key: keyInput.trim() }, 'API key saved.')) {
                    setKeyInput('')
                  }
                }}
              >
                Save key
              </button>
              {auth.key_masked && (
                <button
                  className="btn-secondary"
                  disabled={saving}
                  onClick={() => save({ anthropic_api_key: '' }, 'API key cleared.')}
                >
                  Clear key
                </button>
              )}
            </div>

            <details className="settings-help">
              <summary>How to get an API key</summary>
              <ol>
                <li>Go to <strong>console.anthropic.com</strong> and sign in or create an account — this is Anthropic's API platform, separate from claude.ai.</li>
                <li>Under <strong>Billing</strong>, add credits. Reading one slide image costs about a cent, so $5–10 lasts a long time.</li>
                <li>Under <strong>API Keys</strong>, create a key and paste it above.</li>
              </ol>
              <p className="settings-note">
                A Claude Pro or Max chat subscription does not include API credits. Without a key, images
                are read by the local llava model instead — it works, but is weaker on dense slides.
              </p>
            </details>

            <h4 className="settings-subheading">Google Gemini</h4>
            <ProviderKey
              label="Gemini"
              keyMasked={settings.gemini_key_masked}
              keyInput={providerKeys.gemini}
              onKeyInput={v => setProviderKeys({ ...providerKeys, gemini: v })}
              onSaveKey={async () => { if (await save({ gemini_api_key: providerKeys.gemini.trim() }, 'Gemini key saved.')) setProviderKeys({ ...providerKeys, gemini: '' }) }}
              onClearKey={() => save({ gemini_api_key: '' }, 'Gemini key cleared.')}
              test={providerTest.gemini}
              onTest={() => testProvider('gemini')}
              saving={saving}
              help="Free key at aistudio.google.com → Get API key. The free tier is rate-limited and Google may use free-tier data to improve its models."
            />

            <h4 className="settings-subheading">OpenAI</h4>
            <ProviderKey
              label="OpenAI"
              keyMasked={settings.openai_key_masked}
              keyInput={providerKeys.openai}
              onKeyInput={v => setProviderKeys({ ...providerKeys, openai: v })}
              onSaveKey={async () => { if (await save({ openai_api_key: providerKeys.openai.trim() }, 'OpenAI key saved.')) setProviderKeys({ ...providerKeys, openai: '' }) }}
              onClearKey={() => save({ openai_api_key: '' }, 'OpenAI key cleared.')}
              test={providerTest.openai}
              onTest={() => testProvider('openai')}
              saving={saving}
              help="Key at platform.openai.com → API keys (prepaid credits required)."
            />

            <h4 className="settings-subheading">Google Drive (OAuth client)</h4>
            <p className="settings-note settings-note-full">
              Lets users connect their own Google Drive. In Google Cloud console create an OAuth client of type
              <strong> Web application</strong> with this redirect URI: <code>{settings.google_redirect_uri}</code>
            </p>
            <label className="settings-field">
              <span>Client ID</span>
              <input
                type="text"
                placeholder={settings.google_client_id || '….apps.googleusercontent.com'}
                value={googleClient.id}
                onChange={e => setGoogleClient({ ...googleClient, id: e.target.value })}
                autoComplete="off"
              />
            </label>
            <label className="settings-field">
              <span>Client secret</span>
              <input
                type="password"
                placeholder={settings.google_client_secret_masked ? `Saved (${settings.google_client_secret_masked}) — paste to replace` : 'GOCSPX-…'}
                value={googleClient.secret}
                onChange={e => setGoogleClient({ ...googleClient, secret: e.target.value })}
                autoComplete="off"
              />
            </label>
            <div className="settings-actions">
              <button
                disabled={saving || (!googleClient.id.trim() && !googleClient.secret.trim())}
                onClick={async () => {
                  const payload = {}
                  if (googleClient.id.trim()) payload.google_client_id = googleClient.id.trim()
                  if (googleClient.secret.trim()) payload.google_client_secret = googleClient.secret.trim()
                  if (await save(payload, 'Google OAuth client saved.')) setGoogleClient({ id: '', secret: '' })
                }}
              >
                Save Google client
              </button>
              {(settings.google_client_id || settings.google_client_secret_masked) && (
                <button className="btn-secondary" disabled={saving} onClick={() => save({ google_client_id: '', google_client_secret: '' }, 'Google OAuth client cleared.')}>
                  Clear
                </button>
              )}
            </div>
            {settings.google_client_id && settings.google_client_secret_masked && (
              <p className="settings-inline-ok">Configured — users can connect their Drive from Settings.</p>
            )}
          </section>

          <DriveSection isAdmin refreshKey={`${settings.google_client_id}|${settings.google_client_secret_masked}`} />

          <section className="settings-section">
            <h3>Models</h3>

            <label className="settings-field">
              <span>Claude vision model</span>
              <select
                value={draft.vision_model}
                onChange={e => setDraft({ ...draft, vision_model: e.target.value })}
              >
                {VISION_MODELS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                {!VISION_MODELS.some(m => m.id === draft.vision_model) && (
                  <option value={draft.vision_model}>{draft.vision_model}</option>
                )}
              </select>
            </label>
            <p className="settings-note">
              Used only when credentials are present. Without them, images fall back to
              llava, then to a local BLIP caption.
            </p>

            <label className="settings-field">
              <span>Transcription (Whisper)</span>
              <select
                value={draft.whisper_model}
                onChange={e => setDraft({ ...draft, whisper_model: e.target.value })}
              >
                {WHISPER_MODELS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
            <p className="settings-note">
              Restart required — the model is loaded once at first use. Anything slower than
              realtime on CPU makes chunks queue up and lag grows across a lecture.
            </p>

            <label className="settings-field">
              <span>Notes &amp; chat</span>
              <select value={draft.text_provider} onChange={e => setDraft({ ...draft, text_provider: e.target.value })}>
                <option value="ollama">Local Ollama — private, runs on this Mac</option>
                <option value="claude" disabled={!settings.auth || settings.auth.source === 'none'}>Claude{!settings.auth || settings.auth.source === 'none' ? ' (no key)' : ''}</option>
                <option value="gemini" disabled={!settings.gemini_key_masked}>Google Gemini{settings.gemini_key_masked ? '' : ' (no key)'}</option>
                <option value="openai" disabled={!settings.openai_key_masked}>OpenAI{settings.openai_key_masked ? '' : ' (no key)'}</option>
              </select>
            </label>
            <p className="settings-note">
              Generates the 60-second notes and answers "Ask about the lecture". Cloud providers receive the
              transcript; Ollama keeps it on this machine. A cloud failure falls back to Ollama.
              {settings.active_text_provider !== settings.text_provider && (
                <> <strong>Currently using {settings.active_text_provider}.</strong></>
              )}
            </p>

            <label className="settings-field">
              <span>Slides &amp; images</span>
              <select value={draft.vision_provider} onChange={e => setDraft({ ...draft, vision_provider: e.target.value })}>
                <option value="claude" disabled={!settings.auth || settings.auth.source === 'none'}>Claude — best at dense slides{!settings.auth || settings.auth.source === 'none' ? ' (no key)' : ''}</option>
                <option value="gemini" disabled={!settings.gemini_key_masked}>Google Gemini{settings.gemini_key_masked ? '' : ' (no key)'}</option>
                <option value="openai" disabled={!settings.openai_key_masked}>OpenAI{settings.openai_key_masked ? '' : ' (no key)'}</option>
                <option value="llava">Local llava only</option>
              </select>
            </label>
            <p className="settings-note">
              Reads uploaded slides and pasted screenshots. Falls back to local llava, then a basic caption.
              {settings.active_vision_provider !== settings.vision_provider && (
                <> <strong>Currently using {settings.active_vision_provider}.</strong></>
              )}
            </p>

            <label className="settings-field">
              <span>Ollama model</span>
              <input type="text" value={draft.ollama_model} onChange={e => setDraft({ ...draft, ollama_model: e.target.value })} />
            </label>
            {(draft.text_provider === 'claude') && (
              <label className="settings-field">
                <span>Claude notes model</span>
                <input type="text" value={draft.claude_text_model} onChange={e => setDraft({ ...draft, claude_text_model: e.target.value })} />
              </label>
            )}
            {(draft.text_provider === 'gemini' || draft.vision_provider === 'gemini') && (
              <>
                <label className="settings-field">
                  <span>Gemini model</span>
                  {geminiModels && geminiModels.length > 0 ? (
                    <select value={draft.gemini_model} onChange={e => setDraft({ ...draft, gemini_model: e.target.value })}>
                      {!geminiModels.some(m => m.id === draft.gemini_model) && (
                        <option value={draft.gemini_model}>{draft.gemini_model} (not in Google's current list)</option>
                      )}
                      {geminiModels.map(m => (
                        <option key={m.id} value={m.id}>{m.label}{m.id.includes('latest') ? ' — auto-updates' : ''} ({m.id})</option>
                      ))}
                    </select>
                  ) : (
                    <input type="text" value={draft.gemini_model} onChange={e => setDraft({ ...draft, gemini_model: e.target.value })} />
                  )}
                </label>
                <p className="settings-note">
                  {geminiModels === null ? 'Loading the model list from Google…'
                    : geminiModels.length === 0 ? 'Could not load the model list from Google — type a model name.'
                    : 'Live list from Google for your key. "Gemini Flash Latest" always tracks the newest Flash release.'}
                  {' '}<button type="button" className="link-button" onClick={loadGeminiModels}>Refresh</button>
                </p>
              </>
            )}
            {(draft.text_provider === 'openai' || draft.vision_provider === 'openai') && (
              <label className="settings-field">
                <span>OpenAI model</span>
                <input type="text" value={draft.openai_model} onChange={e => setDraft({ ...draft, openai_model: e.target.value })} />
              </label>
            )}

            <label className="settings-field">
              <span>Notes interval (seconds)</span>
              <input
                type="number"
                min="10"
                value={draft.notes_interval_seconds}
                onChange={e => setDraft({ ...draft, notes_interval_seconds: Number(e.target.value) })}
              />
            </label>

            <label className="settings-field">
              <span>Audio retention (days)</span>
              <input
                type="number"
                min="1"
                value={draft.audio_retention_days}
                onChange={e => setDraft({ ...draft, audio_retention_days: Number(e.target.value) })}
              />
            </label>
            <p className="settings-note">
              Recordings older than this are deleted automatically (transcripts and notes stay). Kept lectures are exempt.
            </p>
            <label className="settings-field">
              <span>Audio storage per user (MB)</span>
              <input
                type="number"
                min="0"
                value={draft.storage_quota_mb}
                onChange={e => setDraft({ ...draft, storage_quota_mb: Number(e.target.value) })}
              />
            </label>
            <label className="settings-field">
              <span>Kept lectures per user</span>
              <input
                type="number"
                min="0"
                value={draft.max_locked_lectures}
                onChange={e => setDraft({ ...draft, max_locked_lectures: Number(e.target.value) })}
              />
            </label>
            <p className="settings-note">
              A kept lecture's audio skips the {draft.audio_retention_days}-day cleanup and it can't be deleted until unlocked. 0 disables keeping for regular users. Admins are never limited.
            </p>
            <p className="settings-note">
              Retained audio only — transcripts and notes never count. 0 means unlimited.
              About 5 MB per lecture hour; audio is also deleted after {draft.audio_retention_days} days. Per-user overrides are set under Users.
            </p>

            <div className="settings-actions">
              <button disabled={saving || !dirty} onClick={() => save(draft, 'Settings saved.')}>
                {saving ? 'Saving…' : 'Save models'}
              </button>
              {dirty && (
                <button
                  className="btn-secondary"
                  onClick={() => setDraft({
                    vision_model: settings.vision_model,
                    ollama_model: settings.ollama_model,
                    text_provider: settings.text_provider,
                    vision_provider: settings.vision_provider,
                    claude_text_model: settings.claude_text_model,
                    gemini_model: settings.gemini_model,
                    openai_model: settings.openai_model,
                    whisper_model: settings.whisper_model,
                    notes_interval_seconds: settings.notes_interval_seconds,
                    storage_quota_mb: settings.storage_quota_mb,
                    registration_open: settings.registration_open,
                    max_locked_lectures: settings.max_locked_lectures,
                  })}
                >
                  Revert
                </button>
              )}
            </div>
          </section>

          <section className="settings-section">
            <h3>Sign-up</h3>
            <label className="switch settings-switch">
              <input
                type="checkbox"
                checked={Boolean(draft.registration_open)}
                onChange={e => setDraft({ ...draft, registration_open: e.target.checked })}
              />
              <span className="switch-track" />
              Allow anyone with the link to create an account
            </label>
            <p className="settings-note settings-note-full">
              Turn this off once everyone is enrolled; admins can still add accounts below.
              {dirty && ' Save with the Save models button above.'}
            </p>
          </section>

          <UsersSection currentUser={user} />

          <section className="settings-section">
            <h3>Ollama</h3>
            <div className={`auth-status ${settings.ollama_reachable ? 'tone-ok' : 'tone-warn'}`}>
              <span className="auth-icon">{settings.ollama_reachable ? <CheckIcon size={13} /> : <AlertIcon size={13} />}</span>
              <div>
                <strong>{settings.ollama_reachable ? 'Reachable' : 'Unreachable'}</strong>
                <p className="auth-detail"><code>{settings.ollama_base_url}</code></p>
                {!settings.ollama_reachable && (
                  <p className="auth-detail">
                    Notes generation falls back to heuristics. Set <code>OLLAMA_BASE_URL</code> in
                    <code> .env</code> — the default <code>localhost</code> is wrong when Ollama
                    runs in a different container.
                  </p>
                )}
              </div>
            </div>
          </section>
        </>
      )}
      <p className="settings-footer">
        <a href="/privacy" target="_blank" rel="noreferrer">Privacy policy</a> — what this app stores and how your Google Drive is used.
      </p>
      </div>
      </div>
    </>
  )
}

export default SettingsPanel
