/**
 * Recording socket to `/ws/session/{id}` with automatic reconnect.
 *
 * Reconnects with exponential backoff (1 s → 15 s) and sends a ping every 30 s
 * so idle proxies don't drop the connection. The URL follows the page's own
 * protocol and host, so it works over a tunnel or reverse proxy unchanged.
 *
 * Audio chunks sent while the socket is down are queued in memory and replayed
 * in order as soon as it reopens (the server keeps chunk numbering per
 * session, so nothing is lost across a server restart). `onReconnect` fires
 * before the replay so the app can re-send its recording options.
 */
import { useEffect, useRef, useState, useCallback } from 'react'

const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_URL = `${WS_PROTOCOL}//${window.location.host}/ws/session`

const HEARTBEAT_INTERVAL = 30000  // 30s
const RECONNECT_BASE_DELAY = 1000 // 1s
const RECONNECT_MAX_DELAY = 15000 // 15s
// ~30 min of 5-second chunks; beyond that the oldest are dropped.
const MAX_QUEUED_CHUNKS = 360

function useWebSocket(sessionId, onMessage, onReconnect) {
  const [isConnected, setIsConnected] = useState(false)
  const [queuedChunks, setQueuedChunks] = useState(0)
  const wsRef = useRef(null)
  const queueRef = useRef([]) // Blobs waiting for the socket
  const wasConnectedRef = useRef(false)
  const onReconnectRef = useRef(onReconnect)
  onReconnectRef.current = onReconnect
  const reconnectTimeoutRef = useRef(null)
  const heartbeatRef = useRef(null)
  const reconnectAttemptsRef = useRef(0)

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
    }
  }, [])

  const startHeartbeat = useCallback(() => {
    clearHeartbeat()
    heartbeatRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL)
  }, [clearHeartbeat])

  const destroyedRef = useRef(false)

  // Send everything queued, oldest first. Only while the socket is open.
  const flushQueue = useCallback(() => {
    const ws = wsRef.current
    while (queueRef.current.length && ws?.readyState === WebSocket.OPEN) {
      ws.send(queueRef.current.shift())
    }
    setQueuedChunks(queueRef.current.length)
  }, [])

  const connect = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    const ws = new WebSocket(`${WS_URL}/${sessionId}`)
    wsRef.current = ws

    ws.onopen = () => {
      if (destroyedRef.current) { ws.close(); return }
      setIsConnected(true)
      reconnectAttemptsRef.current = 0
      startHeartbeat()
      if (wasConnectedRef.current) onReconnectRef.current?.()
      wasConnectedRef.current = true
      flushQueue()
    }

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'pong') return
        onMessage(message)
      } catch (error) {
        console.error('Error parsing message:', error)
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      clearHeartbeat()
      if (destroyedRef.current) return

      const attempts = reconnectAttemptsRef.current
      const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempts), RECONNECT_MAX_DELAY)
      reconnectAttemptsRef.current = attempts + 1

      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, delay)
    }

    ws.onerror = () => {}
  }, [sessionId, onMessage, startHeartbeat, clearHeartbeat, flushQueue])

  useEffect(() => {
    destroyedRef.current = false
    wasConnectedRef.current = false
    queueRef.current = []
    setQueuedChunks(0)
    const t = setTimeout(connect, 50)

    return () => {
      destroyedRef.current = true
      clearTimeout(t)
      clearHeartbeat()
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect, clearHeartbeat])

  // Control messages (start/stop) share the queue with audio so "stop" can't
  // overtake chunks recorded before it. `immediate` bypasses the queue — used
  // for the resume message, which must precede the replayed chunks.
  const sendMessage = useCallback((message, immediate = false) => {
    const text = JSON.stringify(message)
    if (immediate) {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(text)
      return
    }
    queueRef.current.push(text)
    flushQueue()
  }, [flushQueue])

  // Audio goes through the queue so ordering is preserved across a reconnect.
  const sendBinary = useCallback((data) => {
    queueRef.current.push(data)
    if (queueRef.current.length > MAX_QUEUED_CHUNKS) queueRef.current.shift()
    flushQueue()
  }, [flushQueue])

  // Drop anything still queued (recording stopped and the user gave up).
  const clearQueue = useCallback(() => {
    queueRef.current = []
    setQueuedChunks(0)
  }, [])

  return { sendMessage, sendBinary, isConnected, queuedChunks, clearQueue }
}

export default useWebSocket
