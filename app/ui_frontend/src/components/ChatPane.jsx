/**
 * "Ask about the lecture": a small chat over the transcript and uploaded
 * documents. Pasting an image (Ctrl/Cmd+V) attaches it to the next question so
 * a vision model can answer about a slide or screenshot.
 */
import ReactMarkdown from 'react-markdown'
import { useState, useRef, useEffect, useCallback } from 'react'
import { ChatIcon, SendIcon, CloseIcon, TrashIcon } from './Icons'
import { useDialog } from './Dialog'

// "gemini/gemini-3.6-flash" → "Gemini", "ollama/llama3" → "local model (llama3)", etc.
const providerLabel = (p) => {
  const [name, model] = String(p).split('/')
  switch (name) {
    case 'gemini': return 'Gemini'
    case 'claude': return 'Claude'
    case 'openai': return 'OpenAI'
    case 'ollama': return `local model${model ? ` (${model})` : ''}`
    case 'llava': return 'local vision model (llava)'
    case 'blip': return 'local caption model'
    case 'no-credits': return 'no API credits'
    default: return name
  }
}

function ChatPane({ sessionId }) {
  const dialog = useDialog()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingImage, setPendingImage] = useState(null) // { base64, mediaType, previewUrl }
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Earlier questions for this lecture are kept on the server; show them when
  // the lecture is (re)opened. The pane is keyed by session id, so this runs
  // once per lecture.
  useEffect(() => {
    let cancelled = false
    fetch(`/api/session/${sessionId}/chat`)
      .then(r => (r.ok ? r.json() : []))
      .then(rows => {
        if (cancelled || !rows.length) return
        setMessages(rows.map(m => ({ id: m.id, role: m.role, text: m.text, provider: m.provider || undefined })))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sessionId])

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
      // Send the recent exchanges so follow-up questions keep their context.
      const history = messages.slice(-8).map(m => ({ role: m.role, text: m.text }))
      const body = { message: text || 'Please describe and analyze this image.', history }
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
        setMessages(prev => {
          // Attach the stored id to the question we just appended, then the answer.
          const next = [...prev]
          for (let k = next.length - 1; k >= 0; k--) {
            if (next[k].role === 'user' && !next[k].id) { next[k] = { ...next[k], id: data.question_id }; break }
          }
          return [...next, {
            id: data.answer_id,
            role: 'assistant',
            text: data.answer || 'No response received.',
            provider: data.provider,
            fallback: data.fallback,
          }]
        })
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', text: `Error: ${err.message}` }])
    } finally {
      setIsLoading(false)
    }
  }

  // Remove one exchange (a question and its answer) — from the server when it
  // was stored, and from the view either way.
  const removeTurn = async (msg, index) => {
    if (msg.id) {
      const response = await fetch(`/api/session/${sessionId}/chat/${msg.id}`, { method: 'DELETE' })
      if (!response.ok && response.status !== 404) {
        dialog.notice({ title: 'Could not delete', message: `HTTP ${response.status}` })
        return
      }
    }
    setMessages(prev => {
      const partner = msg.role === 'user' ? index + 1 : index - 1
      return prev.filter((m, i) => i !== index && !(prev[partner] && i === partner && prev[partner].role !== msg.role))
    })
  }

  const clearChat = async () => {
    const ok = await dialog.confirm({
      title: 'Clear this conversation?',
      message: 'All questions and answers for this lecture are removed — from the export too. The transcript and notes are not affected.',
      confirmLabel: 'Clear',
      danger: true,
    })
    if (!ok) return
    const response = await fetch(`/api/session/${sessionId}/chat`, { method: 'DELETE' })
    if (!response.ok) {
      dialog.notice({ title: 'Could not clear', message: `HTTP ${response.status}` })
      return
    }
    setMessages([])
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
        {messages.length > 0 && (
          <span className="pane-meta pane-actions">
            <button className="btn-icon" onClick={clearChat} disabled={isLoading} data-tip="Clear the whole conversation" aria-label="Clear conversation"><TrashIcon size={14} /></button>
          </span>
        )}
      </header>
      <div className="pane-body chat-messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>Questions are answered from the transcript and any slides you add. Paste an image to ask about it.</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={msg.id || i} className={`chat-message ${msg.role}`}>
            <span className="chat-role">
              {msg.role === 'user' ? 'You' : 'AI'}
              <button
                type="button"
                className="chat-remove"
                onClick={() => removeTurn(msg, i)}
                disabled={isLoading}
                data-tip="Remove this question and its answer"
                aria-label="Remove this exchange"
              >
                <CloseIcon size={12} />
              </button>
            </span>
            {msg.imageUrl && (
              <img src={msg.imageUrl} alt="pasted" className="chat-image-preview" />
            )}
            {msg.text !== '(image)' && (
              msg.role === 'assistant'
                ? <div className="chat-markdown"><ReactMarkdown>{msg.text}</ReactMarkdown></div>
                : <p>{msg.text}</p>
            )}
            {msg.role === 'assistant' && msg.provider && (
              <span className={`chat-provider${msg.fallback ? ' chat-provider-fallback' : ''}`}>
                {providerLabel(msg.provider)}
                {msg.fallback && <> — {msg.fallback}</>}
              </span>
            )}
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
