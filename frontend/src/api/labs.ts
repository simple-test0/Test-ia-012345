import api, { downloadFile } from './client'

export const getArchitectures = (vram_mb = 0, task_type = '') =>
  api.get('/labs/architectures', { params: { vram_mb, task_type } }).then(r => r.data)

export const getDatasets = () => api.get('/labs/datasets').then(r => r.data)
export const downloadHFDataset = (data: { name: string; hf_id: string; task_type: string }) =>
  api.post('/labs/datasets/huggingface', data).then(r => r.data)
export const uploadDataset = (name: string, files: File[], onProgress?: (pct: number) => void) => {
  const form = new FormData()
  form.append('name', name)
  files.forEach((f) => form.append('files', f, f.name))
  return api
    .post('/labs/datasets/upload', form, {
      timeout: 0, // large uploads can take a while
      onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
    })
    .then(r => r.data)
}
export const deleteDataset = (id: string) => api.delete(`/labs/datasets/${id}`).then(r => r.data)

export const getRuns = () => api.get('/labs/runs').then(r => r.data)
export const getRun = (id: string) => api.get(`/labs/runs/${id}`).then(r => r.data)
export const createRun = (data: object) => api.post('/labs/runs', data).then(r => r.data)
export const pauseRun = (id: string) => api.post(`/labs/runs/${id}/pause`).then(r => r.data)
export const resumeRun = (id: string) => api.post(`/labs/runs/${id}/resume`).then(r => r.data)
export const stopRun = (id: string) => api.post(`/labs/runs/${id}/stop`).then(r => r.data)
export const deleteRun = (id: string) => api.delete(`/labs/runs/${id}`).then(r => r.data)
export const exportRun = (id: string, format: string) =>
  api.post(`/labs/runs/${id}/export`, { format }, { timeout: 0 }).then(r => r.data)
export const downloadExport = (id: string, format: string) =>
  downloadFile(`/labs/runs/${id}/export/download?format=${format}`, `model_${id.slice(0, 8)}.${format}`)
