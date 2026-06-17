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
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage
  // Set during teardown so a socket we close ourselves never schedules a reconnect.
  const closingRef = useRef(false)

  const connect = useCallback(() => {
    if (!url || !enabled) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = (evt) => {
      setConnected(false)
      // No reconnect if we're tearing down, the consumer is disabled, or the
      // server closed cleanly (code 1000).
      if (closingRef.current || !enabled || evt.code === 1000) return
      reconnectTimeout.current = setTimeout(connect, 2000)
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
    closingRef.current = false
    connect()
    return () => {
      closingRef.current = true
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
