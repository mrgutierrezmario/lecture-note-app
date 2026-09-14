// Start/Stop button and the grouped export buttons (notes, transcript, MP3).
// Exports are plain links to the API's attachment endpoints so the browser's
// download manager handles them (blob URLs misbehaved on Android).
import { NotesIcon, TranscriptIcon, AudioIcon } from './Icons'

function RecordingControls({ isRecording, onStart, onStop, onExport, onExportTranscript, onExportAudio, hasNotes, hasTranscript, isConnected, readOnly = false }) {
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
        <button onClick={onExportAudio} disabled={!hasTranscript} data-tip="Download the recording as MP3 (converted on demand)">
          <AudioIcon />
          MP3
        </button>
      </div>
    </div>
  )
}

export default RecordingControls
