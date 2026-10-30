import api from './client'

export interface AgentSessionSummary {
  id: string
  name: string
  model_id: string
  message_count: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentSessionDetail {
  id: string
  name: string
  model_id: string
  system_prompt: string
  messages: { role: 'user' | 'assistant'; content: string }[]
  tools_used: string[]
}

export const getOllamaModels = (): Promise<{ available: boolean; models: string[] }> =>
  api.get('/agent/models').then(r => r.data)
export const getTools = () => api.get('/agent/tools').then(r => r.data)
export const getSessions = (): Promise<AgentSessionSummary[]> =>
  api.get('/agent/sessions').then(r => r.data)
export const getSession = (id: string): Promise<AgentSessionDetail> =>
  api.get(`/agent/sessions/${id}`).then(r => r.data)
export const createSession = (data: {
  name: string
  model_id: string
  system_prompt: string
}): Promise<AgentSessionSummary> => api.post('/agent/sessions', data).then(r => r.data)
export const updateSession = (
  id: string,
  data: Partial<{ name: string; model_id: string; system_prompt: string }>,
): Promise<AgentSessionSummary> => api.patch(`/agent/sessions/${id}`, data).then(r => r.data)
export const deleteSession = (id: string) => api.delete(`/agent/sessions/${id}`).then(r => r.data)
