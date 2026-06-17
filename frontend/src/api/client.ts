import axios from 'axios'

// Optional shared token (set VITE_API_TOKEN at build time to enable auth).
const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? ''

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

if (API_TOKEN) {
  api.interceptors.request.use((config) => {
    config.headers = config.headers ?? {}
    config.headers['X-API-Token'] = API_TOKEN
    return config
  })
}

export default api

export const WS_BASE = `ws://${window.location.host}`

/** Build a WebSocket URL, appending the auth token when configured. */
export const wsUrl = (path: string): string =>
  API_TOKEN ? `${WS_BASE}${path}?token=${encodeURIComponent(API_TOKEN)}` : `${WS_BASE}${path}`
