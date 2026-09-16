// Start/Pause/Stop buttons and the grouped export buttons (notes, transcript,
// MP3). Exports are plain links to the API's attachment endpoints so the
// browser's download manager handles them (blob URLs misbehaved on Android).
import { NotesIcon, TranscriptIcon, AudioIcon, SpinnerIcon, PauseIcon, PlayIcon } from './Icons'

function RecordingControls({ isRecording, isPaused = false, onStart, onStop, onPause, onResume, onExport, onExportTranscript, onExportAudio, hasNotes, hasTranscript, isConnected, readOnly = false, mp3Progress = null }) {
  return (
    <div className="controls">
      {readOnly ? null : !isRecording ? (
        <button
          className="btn-primary btn-record"
          onClick={onStart}
          disabled={!isConnected}
          data-tip={hasTranscript
            ? 'Keep recording into this same lecture — the transcript and notes continue'
            : 'Start recording — transcript appears live, notes build as you go'}
        >
          <span className="record-dot" />
          {hasTranscript ? 'Continue recording' : 'Start recording'}
        </button>
      ) : (
        <>
          {isPaused ? (
            <button className="btn-primary btn-record" onClick={onResume} data-tip="Resume — picks up exactly where you paused">
              <PlayIcon size={14} />
              Resume
            </button>
          ) : (
            <button className="btn-secondary btn-pause" onClick={onPause} data-tip="Pause — nothing is recorded until you resume; the lecture stays open">
              <PauseIcon size={14} />
              Pause
            </button>
          )}
          <button className="btn-primary btn-stop" onClick={onStop} data-tip="Stop recording and generate the final notes">
            <span className={`record-dot${isPaused ? '' : ' recording'}`} />
            Stop recording
          </button>
        </>
      )}

      <div className="btn-group" role="group" aria-label="Export">
        <button onClick={onExport} disabled={!hasNotes} data-tip="Download the notes as a Markdown file">
          <NotesIcon />
          Notes
        </button>
        <button onClick={onExportTranscript} disabled={!hasTranscript} data-tip="Download the full transcript as text">
          <TranscriptIcon />
          Transcript
        </button>
        <button
          onClick={onExportAudio}
          disabled={!hasTranscript || Boolean(mp3Progress)}
          className={mp3Progress ? 'btn-busy' : ''}
          data-tip={mp3Progress ? 'Building the MP3 on the server…' : 'Download the recording as MP3 (built on demand)'}
        >
          {mp3Progress ? <SpinnerIcon /> : <AudioIcon />}
          {mp3Progress
            ? (mp3Progress.phase === 'converting' ? 'Converting…' : `Preparing ${mp3Progress.percent}%`)
            : 'MP3'}
        </button>
      </div>
    </div>
  )
}

export default RecordingControls
