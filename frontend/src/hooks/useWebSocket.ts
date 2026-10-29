import { useCallback, useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: unknown) => void
  /** Called on every (re)connection — useful to resync state. */
  onOpen?: () => void
  enabled?: boolean
}

const MAX_BACKOFF_MS = 15_000

/**
 * WebSocket with automatic reconnection (exponential backoff).
 *
 * Reconnects only while the component is mounted and the URL unchanged, so
 * leaving a page or finishing a job never leaves a socket retrying forever.
 */
export function useWebSocket(url: string | null, options: UseWebSocketOptions = {}) {
  const { enabled = true } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const onMessageRef = useRef(options.onMessage)
  const onOpenRef = useRef(options.onOpen)
  onMessageRef.current = options.onMessage
  onOpenRef.current = options.onOpen

  useEffect(() => {
    if (!url || !enabled) return
    let disposed = false
    let attempt = 0
    let timer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (disposed) return
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        attempt = 0
        setConnected(true)
        onOpenRef.current?.()
      }
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        setConnected(false)
        if (disposed) return
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt) + Math.random() * 300
        attempt += 1
        timer = setTimeout(connect, delay)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (evt) => {
        try {
          onMessageRef.current?.(JSON.parse(evt.data))
        } catch {
          // ignore malformed frames
        }
      }
    }

    // Reconnect right away when the network or the tab comes back.
    const wake = () => {
      if (disposed || wsRef.current) return
      if (timer) clearTimeout(timer)
      attempt = 0
      connect()
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') wake()
    }
    window.addEventListener('online', wake)
    document.addEventListener('visibilitychange', onVisible)

    connect()
    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
      window.removeEventListener('online', wake)
      document.removeEventListener('visibilitychange', onVisible)
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        ws.onclose = null
        ws.close()
      }
      setConnected(false)
    }
  }, [url, enabled])

  /** Returns false when the socket is not open (message not sent). */
  const send = useCallback((data: unknown): boolean => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
      return true
    }
    return false
  }, [])

  return { connected, send }
}
