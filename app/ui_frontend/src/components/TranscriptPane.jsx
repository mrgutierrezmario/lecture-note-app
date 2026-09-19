// Live transcript: new segments append as chunks are transcribed. The pane
// follows along only while the reader is at the bottom; once they scroll up
// to re-read something it stays put (a "Jump to latest" pill brings them
// back). Scrolling is done on the pane itself, never with scrollIntoView,
// which on phones drags the whole page down as well.
import { useEffect, useRef, useState, useCallback } from 'react'
import { TranscriptIcon, MicIcon } from './Icons'

const FOLLOW_THRESHOLD = 48 // px from the bottom that still counts as "at the bottom"

function TranscriptPane({ transcript }) {
  const bodyRef = useRef(null)
  const followRef = useRef(true)
  const [behind, setBehind] = useState(false) // new text arrived while scrolled up

  const scrollToEnd = useCallback((smooth = true) => {
    const el = bodyRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    followRef.current = true
    setBehind(false)
  }, [])

  const onScroll = useCallback(() => {
    const el = bodyRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_THRESHOLD
    followRef.current = atBottom
    if (atBottom) setBehind(false)
  }, [])

  useEffect(() => {
    if (followRef.current) {
      const t = setTimeout(() => scrollToEnd(true), 100)
      return () => clearTimeout(t)
    }
    if (transcript.length) setBehind(true)
  }, [transcript, scrollToEnd])

  return (
    <section className="pane">
      <header className="pane-header">
        <div className="pane-title">
          <span className="pane-icon pane-icon-blue"><TranscriptIcon /></span>
          <h2>Live transcript</h2>
        </div>
        <span className="pane-meta">
          {transcript.length === 1 && String(transcript[0].id).endsWith('-full')
            ? 'Full transcript'
            : `${transcript.length} ${transcript.length === 1 ? 'segment' : 'segments'}`}
        </span>
      </header>
      <div ref={bodyRef} onScroll={onScroll} className="pane-body">
        {transcript.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon"><MicIcon size={22} strokeWidth={1.6} /></span>
            <strong>Nothing transcribed yet</strong>
            <p>Press Start recording and speech will appear here in real time.</p>
          </div>
        ) : (
          <div className="transcript-text">
            {transcript.map((segment, index) => (
              <span
                key={segment.id || index}
                className={index === transcript.length - 1 ? 'new-segment' : ''}
              >
                {segment.text}{' '}
              </span>
            ))}
          </div>
        )}
        {behind && (
          <button type="button" className="jump-latest" onClick={() => scrollToEnd(true)}>
            ↓ Jump to latest
          </button>
        )}
      </div>
    </section>
  )
}

export default TranscriptPane
