import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

/**
 * Themed replacement for window.confirm / prompt / alert.
 *
 *   const dialog = useDialog()
 *   if (await dialog.confirm({ title, message, confirmLabel, danger: true })) …
 *   const value = await dialog.prompt({ title, label, defaultValue, type })   // null = cancelled
 *   await dialog.notice({ title, message })
 */
const DialogContext = createContext(null)

export function DialogProvider({ children }) {
  const [state, setState] = useState(null) // { kind, options, resolve }

  const open = useCallback((kind, options) =>
    new Promise(resolve => setState({ kind, options, resolve })), [])

  const api = useRef({
    confirm: opts => open('confirm', opts),
    prompt: opts => open('prompt', opts),
    notice: opts => open('notice', opts),
  }).current

  const close = (result) => {
    state?.resolve(result)
    setState(null)
  }

  return (
    <DialogContext.Provider value={api}>
      {children}
      {state && <DialogBox kind={state.kind} options={state.options} onClose={close} />}
    </DialogContext.Provider>
  )
}

export const useDialog = () => useContext(DialogContext)

function DialogBox({ kind, options, onClose }) {
  const {
    title, message, label, defaultValue = '', placeholder, type = 'text',
    confirmLabel = kind === 'confirm' ? 'Confirm' : 'OK', cancelLabel = 'Cancel', danger = false,
  } = options
  const [value, setValue] = useState(defaultValue)
  const inputRef = useRef(null)
  const confirmRef = useRef(null)

  useEffect(() => {
    (kind === 'prompt' ? inputRef : confirmRef).current?.focus()
    const onKey = e => { if (e.key === 'Escape') onClose(kind === 'prompt' ? null : false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [kind, onClose])

  const submit = (e) => {
    e?.preventDefault()
    onClose(kind === 'prompt' ? value : true)
  }
  const cancel = () => onClose(kind === 'prompt' ? null : false)

  return (
    <div className="dialog-backdrop" onClick={cancel}>
      <form
        className={`dialog${danger ? ' dialog-danger' : ''}`}
        role={kind === 'notice' ? 'alertdialog' : 'dialog'}
        aria-labelledby="dialog-title"
        onClick={e => e.stopPropagation()}
        onSubmit={submit}
      >
        <h2 id="dialog-title">{title}</h2>
        {message && <p className="dialog-message">{message}</p>}
        {kind === 'prompt' && (
          <label className="dialog-field">
            {label && <span>{label}</span>}
            <input
              ref={inputRef}
              type={type}
              value={value}
              placeholder={placeholder}
              onChange={e => setValue(e.target.value)}
              autoComplete="off"
            />
          </label>
        )}
        <div className="dialog-actions">
          {kind !== 'notice' && (
            <button type="button" className="btn-secondary" onClick={cancel}>{cancelLabel}</button>
          )}
          <button ref={confirmRef} type="submit" className={danger ? 'btn-danger' : 'btn-primary'}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  )
}
