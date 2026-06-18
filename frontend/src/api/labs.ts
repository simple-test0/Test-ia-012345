import api from './client'

export const getArchitectures = (vram_mb = 0, task_type = '') =>
  api.get('/labs/architectures', { params: { vram_mb, task_type } }).then(r => r.data)

export const getDatasets = () => api.get('/labs/datasets').then(r => r.data)
export const downloadHFDataset = (data: { name: string; hf_id: string; task_type: string }) =>
  api.post('/labs/datasets/huggingface', data).then(r => r.data)

export const getRuns = () => api.get('/labs/runs').then(r => r.data)
export const getRun = (id: string) => api.get(`/labs/runs/${id}`).then(r => r.data)
export const createRun = (data: object) => api.post('/labs/runs', data).then(r => r.data)
export const pauseRun = (id: string) => api.post(`/labs/runs/${id}/pause`).then(r => r.data)
export const resumeRun = (id: string) => api.post(`/labs/runs/${id}/resume`).then(r => r.data)
export const stopRun = (id: string) => api.post(`/labs/runs/${id}/stop`).then(r => r.data)
export const exportRun = (id: string, format: string) =>
  api.post(`/labs/runs/${id}/export`, { format }).then(r => r.data)

export const deleteDataset = (id: string) =>
  api.delete(`/labs/datasets/${id}`).then(r => r.data)

export const uploadDataset = (formData: FormData) =>
  api.post('/labs/datasets/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)

export const downloadExport = (runId: string) =>
  api.get(`/labs/runs/${runId}/export/download`, { responseType: 'blob' }).then(r => r.data)
