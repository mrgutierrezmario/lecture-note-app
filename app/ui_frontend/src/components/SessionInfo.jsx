// Lecture title field, the "key terms" button (spelling hints for the
// transcriber) and the short session id chip in the app bar.
import { useEffect, useRef } from 'react'
import { TermsIcon } from './Icons'

function SessionInfo({ sessionId, title, onTitleChange, disabled, vocabulary = '', onEditVocabulary }) {
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
      {onEditVocabulary && (
        <button
          type="button"
          className={`btn-icon terms-button${vocabulary ? ' btn-icon-active' : ''}`}
          onClick={onEditVocabulary}
          aria-label="Key terms for this lecture"
          data-tip={vocabulary
            ? `Key terms: ${vocabulary.length > 60 ? vocabulary.slice(0, 60) + '…' : vocabulary} — click to edit`
            : 'Key terms — names, acronyms and course terms so the transcript spells them right'}
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
