// Start/Stop button and the grouped export buttons (notes, transcript, MP3).
// Exports are plain links to the API's attachment endpoints so the browser's
// download manager handles them (blob URLs misbehaved on Android).
import { NotesIcon, TranscriptIcon, AudioIcon, SpinnerIcon } from './Icons'

function RecordingControls({ isRecording, onStart, onStop, onExport, onExportTranscript, onExportAudio, hasNotes, hasTranscript, isConnected, readOnly = false, mp3Progress = null }) {
  return (
    <div className="controls">
      {readOnly ? null : !isRecording ? (
        <button className="btn-primary btn-record" onClick={onStart} disabled={!isConnected} data-tip="Start recording — transcript appears live, notes every 60 s">
          <span className="record-dot" />
          Start recording
        </button>
      ) : (
        <button className="btn-primary btn-stop" onClick={onStop} data-tip="Stop recording and generate the final notes">
          <span className="record-dot recording" />
          Stop recording
        </button>
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
