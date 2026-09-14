/**
 * Recording socket to `/ws/session/{id}` with automatic reconnect.
 *
 * Reconnects with exponential backoff (3 s → 30 s) and sends a ping every 30 s
 * so idle proxies don't drop the connection. The URL follows the page's own
 * protocol and host, so it works over a tunnel or reverse proxy unchanged.
 */
import { useEffect, useRef, useState, useCallback } from 'react'

const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_URL = `${WS_PROTOCOL}//${window.location.host}/ws/session`

const HEARTBEAT_INTERVAL = 30000  // 30s
const RECONNECT_BASE_DELAY = 3000 // 3s
const RECONNECT_MAX_DELAY = 30000 // 30s

function useWebSocket(sessionId, onMessage) {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef(null)
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
  }, [sessionId, onMessage, startHeartbeat, clearHeartbeat])

  useEffect(() => {
    destroyedRef.current = false
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

  const sendMessage = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  const sendBinary = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data)
    }
  }, [])

  return { sendMessage, sendBinary, isConnected }
}

export default useWebSocket
