import api from './client'

export interface ImageModel {
  id: string
  name: string
  description?: string
  source: 'curated' | 'downloaded'
  recommended: boolean
  status: 'ready' | 'downloading' | 'error'
  compatible: boolean
  repo_id: string
  tags?: string[]
  gated?: boolean
  min_vram_mb?: number
  recommended_steps?: number
  default_cfg?: number
  default_width?: number
  default_height?: number
  progress?: number
  error_message?: string | null
}

export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ImageJob {
  job_id: string
  status: JobStatus
  model_id: string
  prompt: string
  negative_prompt?: string
  width: number
  height: number
  steps: number
  cfg_scale?: number
  seed: number
  sampler?: string
  num_images?: number
  init_image?: string | null // img2img source URL
  strength?: number | null
  images: string[] // thumbnail URLs
  full_images: string[] // full-resolution URLs
  error_message?: string | null
  duration_ms?: number | null
  created_at: string | null
  queue_position?: number | null
}

export interface GenerateParams {
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
  init_image?: string // data URL (img2img)
  strength?: number
}

export const getModels = (): Promise<ImageModel[]> => api.get('/image/models').then(r => r.data)

export const getSamplers = (): Promise<string[]> => api.get('/image/samplers').then(r => r.data)

export const generateImage = (
  params: GenerateParams,
): Promise<{
  job_id: string
  status: JobStatus
  seed: number
  queue_position: number
  width: number
  height: number
  init_image: string | null
}> =>
  api.post('/image/generate', params).then(r => r.data)

export const getJobs = (limit = 20, offset = 0): Promise<ImageJob[]> =>
  api.get('/image/jobs', { params: { limit, offset } }).then(r => r.data)

export const getJob = (jobId: string): Promise<ImageJob> =>
  api.get(`/image/jobs/${jobId}`).then(r => r.data)

export const cancelJob = (jobId: string) =>
  api.post(`/image/jobs/${jobId}/cancel`).then(r => r.data)

export const deleteJob = (jobId: string) =>
  api.delete(`/image/jobs/${jobId}`).then(r => r.data)

// ── Hugging Face connector ──────────────────────────────────────────────────

export const searchHFModels = (query: string, limit = 25) =>
  api.get('/image/hf/search', { params: { query, limit } }).then(r => r.data.results)

export const downloadHFModel = (data: { repo_id: string; name?: string }) =>
  api.post('/image/hf/download', data).then(r => r.data)

export const getHFModelStatus = (modelId: string): Promise<ImageModel> =>
  api.get(`/image/hf/models/${modelId}`).then(r => r.data)

export const deleteHFModel = (modelId: string) =>
  api.delete(`/image/hf/models/${modelId}`).then(r => r.data)
