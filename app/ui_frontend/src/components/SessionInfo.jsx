// Lecture title field, the "key terms" button (spelling hints for the
// transcriber) and the short session id chip in the app bar.
import { useEffect, useRef } from 'react'
import { TermsIcon } from './Icons'

function SessionInfo({ sessionId, title, onTitleChange, disabled, vocabulary = '', notesFocus = '', onEditDetails }) {
  const inputRef = useRef(null)

  // Put the cursor in the title field for each new lecture — but not on touch
  // devices, where focusing would pop the keyboard over the page on load.
  useEffect(() => {
    if (disabled) return
    if (window.matchMedia?.('(pointer: coarse)').matches) return
    inputRef.current?.focus()
  }, [sessionId, disabled])

  return (
    <div className="session-info">
      <input
        id="lecture-title"
        ref={inputRef}
        type="text"
        className="title-input"
        placeholder="Name your lecture…"
        aria-label="Lecture title"
        value={title}
        onChange={(e) => onTitleChange(e.target.value)}
        disabled={disabled}
      />
      {onEditDetails && (
        <button
          type="button"
          className={`btn-icon terms-button${vocabulary || notesFocus ? ' btn-icon-active' : ''}`}
          onClick={onEditDetails}
          aria-label="Lecture details: key terms and notes focus"
          data-tip={[
            vocabulary ? `Key terms: ${vocabulary.length > 50 ? vocabulary.slice(0, 50) + '…' : vocabulary}` : null,
            notesFocus ? `Focus: ${notesFocus.length > 50 ? notesFocus.slice(0, 50) + '…' : notesFocus}` : null,
          ].filter(Boolean).join(' · ') || 'Lecture details — key terms for the transcript and a focus for the notes'}
        >
          <TermsIcon size={16} />
        </button>
      )}
      <span className="session-chip" title={`Session ${sessionId}`}>
        <span>session</span>
        <code>{sessionId.slice(0, 8)}</code>
      </span>
    </div>
  )
}

export default SessionInfo
