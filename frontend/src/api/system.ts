import api from './client'

export interface LogEntry {
  id: number
  ts: number
  level: string
  logger: string
  message: string
}

export const getLogs = (limit = 500): Promise<{ logs: LogEntry[] }> =>
  api.get('/system/logs', { params: { limit } }).then((r) => r.data)

export const shutdownApp = (): Promise<{ status: string }> =>
  api.post('/system/shutdown').then((r) => r.data)
