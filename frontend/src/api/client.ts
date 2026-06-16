import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

export default api

export const WS_BASE = `ws://${window.location.host}`
