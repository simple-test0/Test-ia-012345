import { useEffect, useState } from 'react'
import { getHardwareInfo, getRecommendations } from '../api/hardware'

export interface GpuInfo {
  index: number
  name: string
  vram_total_mb: number
  vram_used_mb: number
  vram_free_mb: number
  utilization_percent: number
}

export interface HardwareInfo {
  accelerator?: 'cuda' | 'mps' | 'cpu'
  cuda_available: boolean
  mps_available?: boolean
  gpus: GpuInfo[]
  ram_total_mb: number
  ram_used_mb: number
  ram_free_mb: number
  cpu: { name: string; logical_cores: number; utilization_percent: number } | null
}

export interface Recommendations {
  tier_label: string
  vram_mb: number
  image_gen: { recommended_models: string[]; max_resolution: number[]; notes: string }
  training: {
    recommended_batch_size: number
    recommended_learning_rate: number
    notes: string
  }
  agent: { recommended_models: string[]; notes: string }
}

// Recommendations never change while the backend runs: fetch them once and
// share them between every component that asks.
let recsPromise: Promise<Recommendations | null> | null = null
export function loadRecommendations(): Promise<Recommendations | null> {
  if (!recsPromise) {
    recsPromise = getRecommendations().catch(() => {
      recsPromise = null // retry next time
      return null
    })
  }
  return recsPromise
}

/** Live hardware usage, polled only while the tab is visible. */
export function useHardwareInfo(pollInterval = 5000) {
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [recommendations, setRecommendations] = useState<Recommendations | null>(null)
  const [loading, setLoading] = useState(true)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const refresh = async () => {
      if (document.visibilityState === 'visible') {
        try {
          const hw = await getHardwareInfo()
          if (cancelled) return
          setHardware(hw)
          setOffline(false)
        } catch {
          if (!cancelled) setOffline(true)
        } finally {
          if (!cancelled) setLoading(false)
        }
      }
      if (!cancelled) timer = setTimeout(refresh, pollInterval)
    }

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        if (timer) clearTimeout(timer)
        refresh()
      }
    }

    refresh()
    loadRecommendations().then((r) => !cancelled && r && setRecommendations(r))
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [pollInterval])

  return { hardware, recommendations, loading, offline }
}
