import api from './client'

export const getModels = () => api.get('/image/models').then(r => r.data)

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
}) => api.post('/image/generate', params).then(r => r.data)

export const getJobs = (limit = 20, offset = 0) =>
  api.get('/image/jobs', { params: { limit, offset } }).then(r => r.data)

export const getJob = (jobId: string) =>
  api.get(`/image/jobs/${jobId}`).then(r => r.data)
