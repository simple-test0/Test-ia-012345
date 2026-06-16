import { useEffect, useRef, useState } from 'react'
import { getHardwareInfo, getRecommendations } from '../api/hardware'

export function useHardwareInfo(pollInterval = 5000) {
  const [hardware, setHardware] = useState<Record<string, unknown> | null>(null)
  const [recommendations, setRecommendations] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = async () => {
    try {
      const [hw, rec] = await Promise.all([getHardwareInfo(), getRecommendations()])
      setHardware(hw)
      setRecommendations(rec)
    } catch {
      // backend not ready yet
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    timerRef.current = setInterval(refresh, pollInterval)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [pollInterval])

  return { hardware, recommendations, loading, refresh }
}
