import { useEffect, useState } from 'react'

/** useState that survives page reloads (localStorage; silently in-memory if unavailable). */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })

  // Written immediately (small values, cheap): nothing is lost on a quick reload.
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // storage full or blocked (private mode): keep working in memory
    }
  }, [key, value])

  return [value, setValue] as const
}
