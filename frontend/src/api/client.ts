import axios from 'axios'

// Optional shared token (set VITE_API_TOKEN at build time to enable auth).
const API_TOKEN: string = import.meta.env.VITE_API_TOKEN ?? ''

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

if (API_TOKEN) {
  api.interceptors.request.use((config) => {
    config.headers.set('X-API-Token', API_TOKEN)
    return config
  })
}

export default api

// wss:// when the page is served over https (reverse proxy, tunnel…).
export const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

/** Build a WebSocket URL, appending the auth token when configured. */
export const wsUrl = (path: string): string =>
  API_TOKEN ? `${WS_BASE}${path}?token=${encodeURIComponent(API_TOKEN)}` : `${WS_BASE}${path}`

/** URL usable directly by the browser (<img src>, download links). */
export const withToken = (url: string): string => {
  if (!API_TOKEN) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(API_TOKEN)}`
}

/** Human-readable message from an API error (uses the backend's `detail`). */
export function errorMessage(err: unknown, fallback = 'Une erreur est survenue'): string {
  if (axios.isAxiosError(err)) {
    if (!err.response) {
      return err.code === 'ECONNABORTED'
        ? 'Le serveur met trop de temps à répondre.'
        : 'Serveur injoignable — le backend est-il démarré ?'
    }
    const detail = (err.response.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) {
      const d = detail[0] as { msg: string; loc?: string[] }
      return d.loc ? `${d.loc[d.loc.length - 1]}: ${d.msg}` : d.msg
    }
    return `${fallback} (HTTP ${err.response.status})`
  }
  return err instanceof Error ? err.message : fallback
}

/** Save a file returned by an authenticated endpoint. */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await api.get(url, { responseType: 'blob', timeout: 0 })
  const href = URL.createObjectURL(res.data as Blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 10_000)
}
