import api from './client'

export const getHardwareInfo = () => api.get('/hardware/info').then(r => r.data)
export const getRecommendations = () => api.get('/hardware/recommendations').then(r => r.data)
