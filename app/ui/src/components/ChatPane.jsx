/**
 * "Ask about the lecture": a small chat over the transcript and uploaded
 * documents. Pasting an image (Ctrl/Cmd+V) attaches it to the next question so
 * a vision model can answer about a slide or screenshot.
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { ChatIcon, SendIcon, CloseIcon } from './Icons'

function ChatPane({ sessionId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingImage, setPendingImage] = useState(null) // { base64, mediaType, previewUrl }
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handlePaste = useCallback((e) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        const reader = new FileReader()
        reader.onload = (ev) => {
          const dataUrl = ev.target.result
          const [header, base64] = dataUrl.split(',')
          const mediaType = header.match(/:(.*?);/)[1]
          setPendingImage({ base64, mediaType, previewUrl: dataUrl })
        }
        reader.readAsDataURL(file)
        break
      }
    }
  }, [])

  const clearImage = useCallback(() => setPendingImage(null), [])

  const sendMessage = async () => {
    const text = input.trim()
    if ((!text && !pendingImage) || isLoading) return

    const userMsg = {
      role: 'user',
      text: text || '(image)',
      imageUrl: pendingImage?.previewUrl || null,
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    const imageToSend = pendingImage
    setPendingImage(null)
    setIsLoading(true)

    try {
      const body = { message: text || 'Please describe and analyze this image.' }
      if (imageToSend) {
        body.image_base64 = imageToSend.base64
        body.image_media_type = imageToSend.mediaType
      }
      const response = await fetch(`/api/session/${sessionId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await response.json()
      if (!response.ok) {
        const detail = data?.detail || `Server error (${response.status})`
        setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${detail}` }])
      } else {
        setMessages(prev => [...prev, { role: 'assistant', text: data.answer || 'No response received.' }])
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${err.message}` }])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <section className="pane chat-pane">
      <header className="pane-header">
        <div className="pane-title">
          <span className="pane-icon pane-icon-cyan"><ChatIcon /></span>
          <h2>Ask about the lecture</h2>
        </div>
      </header>
      <div className="pane-body chat-messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>Questions are answered from the transcript and any slides you add. Paste an image to ask about it.</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <span className="chat-role">{msg.role === 'user' ? 'You' : 'AI'}</span>
            {msg.imageUrl && (
              <img src={msg.imageUrl} alt="pasted" className="chat-image-preview" />
            )}
            <p>{msg.text !== '(image)' ? msg.text : ''}</p>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message assistant">
            <span className="chat-role">AI</span>
            <p className="chat-thinking">Thinking…</p>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-footer">
        {pendingImage && (
          <div className="chat-image-pending">
            <img src={pendingImage.previewUrl} alt="pending" className="chat-image-preview" />
            <button className="btn-remove-image" onClick={clearImage} aria-label="Remove image">
              <CloseIcon size={11} />
            </button>
          </div>
        )}
        <div className="chat-input-row">
          <textarea
            ref={textareaRef}
            className="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="Ask a question or paste an image…"
            rows={1}
            disabled={isLoading}
          />
          <button
            className="btn-send"
            onClick={sendMessage}
            disabled={isLoading || (!input.trim() && !pendingImage)}
            aria-label="Send"
          >
            <SendIcon size={18} />
          </button>
        </div>
      </div>
    </section>
  )
}

export default ChatPane
