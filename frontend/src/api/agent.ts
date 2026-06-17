import api from './client'

export const getOllamaModels = () => api.get('/agent/models').then(r => r.data)
export const getTools = () => api.get('/agent/tools').then(r => r.data)
export const getSessions = () => api.get('/agent/sessions').then(r => r.data)
export const getSession = (id: string) => api.get(`/agent/sessions/${id}`).then(r => r.data)
export const createSession = (data: { name: string; model_id: string; system_prompt: string }) =>
  api.post('/agent/sessions', data).then(r => r.data)
export const deleteSession = (id: string) => api.delete(`/agent/sessions/${id}`).then(r => r.data)
export const renameSession = (id: string, name: string) =>
  api.patch(`/agent/sessions/${id}`, { name }).then(r => r.data)
