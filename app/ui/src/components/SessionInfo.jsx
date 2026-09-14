// Lecture title field and the short session id chip in the app bar.
import { useEffect, useRef } from 'react'

function SessionInfo({ sessionId, title, onTitleChange, disabled }) {
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
      <span className="session-chip" title={`Session ${sessionId}`}>
        <span>session</span>
        <code>{sessionId.slice(0, 8)}</code>
      </span>
    </div>
  )
}

export default SessionInfo
