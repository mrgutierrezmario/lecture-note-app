/**
 * Drag-and-drop / browse uploader for slides and documents (PDF, PowerPoint,
 * Word, images). The backend extracts or transcribes the text and uses it as
 * chat context; the list below the drop zone shows what has been attached.
 */
import { useState, useRef } from 'react'
import { UploadIcon, FileIcon } from './Icons'

const ACCEPT = '.pdf,.pptx,.ppt,.docx,.png,.jpg,.jpeg,.webp,.gif'

function FileUpload({ sessionId }) {
  const [uploads, setUploads] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  const upload = async (file) => {
    if (!file) return
    setIsUploading(true)
    setError(null)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const response = await fetch(`/api/session/${sessionId}/documents`, {
        method: 'POST',
        body: formData,
      })
      if (response.ok) {
        const data = await response.json()
        setUploads(prev => [...prev, { filename: data.filename, id: data.id }])
      } else {
        setError('Upload failed: unsupported file type or error processing file.')
      }
    } catch (err) {
      setError(`Upload error: ${err.message}`)
    } finally {
      setIsUploading(false)
    }
  }

  const handleFileChange = async (e) => {
    await upload(e.target.files[0])
    e.target.value = ''
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    if (isUploading) return
    upload(e.dataTransfer.files[0])
  }

  return (
    <div className="file-upload">
      <div
        className={`dropzone${isDragging ? ' dragging' : ''}`}
        onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <span className="pane-icon pane-icon-blue dropzone-icon"><UploadIcon size={18} /></span>
        <div className="dropzone-text">
          <strong>Add slides to this lecture</strong>
          <span>{isUploading ? 'Uploading… (images take a few seconds to read)' : 'Drop a PDF, PowerPoint, Word file or image, or browse'}</span>
        </div>
        <button
          className="btn-secondary"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
        >
          Browse
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>
      {error && <p className="upload-error">{error}</p>}
      {uploads.length > 0 && (
        <ul className="upload-list">
          {uploads.map(u => (
            <li key={u.id} className="upload-item"><FileIcon size={14} /> {u.filename}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default FileUpload
