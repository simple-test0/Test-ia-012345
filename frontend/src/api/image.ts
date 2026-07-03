import api from './client'

export const getModels = () => api.get('/image/models').then(r => r.data)

export type GenerationMode = 'txt2img' | 'img2img' | 'controlnet'
export type ControlNetType = 'canny' | 'depth' | 'pose'

export const generateImage = (params: {
  model_id: string
  prompt: string
  negative_prompt?: string
  width: number
  height: number
  steps: number
  cfg_scale: number
  seed: number
  sampler: string
  num_images: number
  lora?: string
  mode?: GenerationMode
  init_image?: string // base64 data URL
  strength?: number
  controlnet_type?: ControlNetType
  control_image?: string // base64 data URL
  preprocess?: boolean
  upscale?: boolean
  upscale_factor?: number
  upscale_strength?: number
}) => api.post('/image/generate', params).then(r => r.data)

export const getJobs = (limit = 20, offset = 0) =>
  api.get('/image/jobs', { params: { limit, offset } }).then(r => r.data)

export const getJob = (jobId: string) =>
  api.get(`/image/jobs/${jobId}`).then(r => r.data)

export const deleteJob = (jobId: string) =>
  api.delete(`/image/jobs/${jobId}`).then(r => r.data)

// ── Manual pipeline (VRAM) management ───────────────────────────────────────

export const getLoadedPipelines = (): Promise<{ loaded: string[] }> =>
  api.get('/image/pipelines').then(r => r.data)

export const loadModel = (modelId: string): Promise<{ status: string }> =>
  api.post(`/image/models/${modelId}/load`).then(r => r.data)

export const unloadModel = (modelId: string): Promise<{ status: string }> =>
  api.post(`/image/models/${modelId}/unload`).then(r => r.data)

// ── Hugging Face connector ──────────────────────────────────────────────────

export const searchHFModels = (query: string, limit = 25) =>
  api.get('/image/hf/search', { params: { query, limit } }).then(r => r.data.results)

export const downloadHFModel = (data: { repo_id: string; name?: string }) =>
  api.post('/image/hf/download', data).then(r => r.data)

export const getHFModelStatus = (modelId: string) =>
  api.get(`/image/hf/models/${modelId}`).then(r => r.data)

export const deleteHFModel = (modelId: string) =>
  api.delete(`/image/hf/models/${modelId}`).then(r => r.data)
