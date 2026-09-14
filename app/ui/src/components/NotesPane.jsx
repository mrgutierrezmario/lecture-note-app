// Rendered Markdown of the latest notes version, with an empty state before the
// first generation pass.
import ReactMarkdown from 'react-markdown'
import { NotesIcon, SparklesIcon } from './Icons'

function NotesPane({ notes, version }) {
  return (
    <section className="pane">
      <header className="pane-header">
        <div className="pane-title">
          <span className="pane-icon pane-icon-teal"><NotesIcon /></span>
          <h2>Notes</h2>
        </div>
        <span className="pane-meta">
          {version > 0 ? `Version ${version}` : 'Generated while you record'}
        </span>
      </header>
      <div className="pane-body">
        {notes ? (
          <div className="notes-content">
            <ReactMarkdown>{notes}</ReactMarkdown>
          </div>
        ) : (
          <div className="empty-state">
            <span className="empty-icon"><SparklesIcon size={22} /></span>
            <strong>Notes will build as you record</strong>
            <p>Structured headings and bullet points are generated from the transcript automatically.</p>
          </div>
        )}
      </div>
    </section>
  )
}

export default NotesPane
