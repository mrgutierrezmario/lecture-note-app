// Live transcript: new segments append as chunks are transcribed and the view
// follows along; a past lecture shows the whole transcript at once.
import { useEffect, useRef } from 'react'
import { TranscriptIcon, MicIcon } from './Icons'

function TranscriptPane({ transcript }) {
  const endRef = useRef(null)
  const scrollTimerRef = useRef(null)

  useEffect(() => {
    if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current)
    scrollTimerRef.current = setTimeout(() => {
      endRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 150)
    return () => clearTimeout(scrollTimerRef.current)
  }, [transcript])

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
      <div className="pane-body">
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
        <div ref={endRef} />
      </div>
    </section>
  )
}

export default TranscriptPane
