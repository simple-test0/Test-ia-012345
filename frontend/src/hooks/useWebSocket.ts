import { useCallback, useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: unknown) => void
  enabled?: boolean
}

export function useWebSocket(url: string | null, options: UseWebSocketOptions = {}) {
  const { onMessage, enabled = true } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shouldReconnect = useRef(true)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (!url || !enabled) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    shouldReconnect.current = true
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      // Don't reconnect if the socket was closed on purpose (unmount/url change).
      if (shouldReconnect.current) {
        reconnectTimeout.current = setTimeout(connect, 2000)
      }
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        onMessageRef.current?.(data)
      } catch {
        // ignore parse errors
      }
    }
  }, [url, enabled])

  useEffect(() => {
    connect()
    return () => {
      shouldReconnect.current = false
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { connected, send }
}
