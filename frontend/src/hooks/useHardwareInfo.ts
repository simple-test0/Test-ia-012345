import { useEffect, useRef, useState } from 'react'
import { getHardwareInfo, getRecommendations } from '../api/hardware'

export function useHardwareInfo(pollInterval = 10000) {
  const [hardware, setHardware] = useState<Record<string, unknown> | null>(null)
  const [recommendations, setRecommendations] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = async () => {
    try {
      setHardware(await getHardwareInfo())
    } catch {
      // backend not ready yet
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Recommendations depend only on total VRAM — fetch once, don't poll.
    getRecommendations()
      .then(setRecommendations)
      .catch(() => {})
    refresh()
    timerRef.current = setInterval(refresh, pollInterval)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollInterval])

  return { hardware, recommendations, loading, refresh }
}
