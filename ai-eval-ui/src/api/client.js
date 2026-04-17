import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function readStoredAccessToken() {
  if (typeof window === 'undefined') {
    return ''
  }

  return window.localStorage.getItem('accessToken') || ''
}

function createClient({ apiKey, accessToken } = {}) {
  const headers = {}
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  const token = accessToken || readStoredAccessToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  return axios.create({
    baseURL: API_BASE_URL,
    headers,
  })
}

export async function getTraces({ projectId, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get('/trace', {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return response.data
}

export async function getDatasets({ projectId, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get('/dataset', {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return response.data
}

export async function createDataset(
  { name, taskType = 'rag', projectId } = {},
  { apiKey } = {},
) {
  const client = createClient({ apiKey })
  const response = await client.post('/dataset', {
    name,
    task_type: taskType,
    project_id: projectId,
  })
  return response.data
}

export async function getDatasetSamples(datasetId, { tag, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/dataset/${datasetId}/samples`, {
    params: tag ? { tag } : undefined,
  })
  return response.data
}

export async function createDatasetSample(datasetId, payload, { apiKey, accessToken } = {}) {
  const client = createClient({ apiKey, accessToken })
  const response = await client.post(`/dataset/${datasetId}/samples`, payload)
  return response.data
}

export async function createDatasetSamplesFromTraces(datasetId, traceIds, { apiKey, accessToken } = {}) {
  const client = createClient({ apiKey, accessToken })
  const response = await client.post(`/dataset/${datasetId}/from-traces`, {
    trace_ids: traceIds,
  })
  return response.data
}

export async function attachTracesToDataset(datasetId, traceIds, { apiKey, accessToken } = {}) {
  const client = createClient({ apiKey, accessToken })
  const response = await client.post(`/dataset/${datasetId}/from-traces`, {
    trace_ids: traceIds,
  })
  return response.data
}

export async function runEval(
  datasetId,
  { metrics = [], provider = 'mock', model = 'mock', projectId, apiKey } = {},
) {
  const client = createClient({ apiKey })
  const response = await client.post(`/eval/${datasetId}`, {
    metrics,
    provider,
    model,
    project_id: projectId,
  })
  return response.data
}

export async function getEvalRuns(datasetId, { projectId, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/eval/runs/${datasetId}`, {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return response.data
}

export async function getProjectEvalRuns(projectId, { apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/eval/project/${projectId}/runs`)
  return response.data
}

export async function getProjectEvalResults(projectId, { apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/eval/project/${projectId}/results`)
  return response.data
}

export async function getEvalRun(evalRunId, { projectId, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/eval/run/${evalRunId}`, {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return response.data
}

export async function runBenchmark(
  datasetId,
  { variants = [], metrics = ['faithfulness', 'groundedness', 'context_precision'], projectId, apiKey } = {},
) {
  const client = createClient({ apiKey })
  const response = await client.post('/benchmark/compare', {
    dataset_id: datasetId,
    variants,
    metrics,
    project_id: projectId,
  })
  return response.data
}

export async function getProjectDashboard(projectId, { apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.get(`/dashboard/project/${projectId}`)
  return response.data
}

export async function evaluateTrace(traceId, { metrics = [], provider = 'mock', model = 'mock', projectId, apiKey } = {}) {
  const client = createClient({ apiKey })
  const response = await client.post(`/eval/trace/${traceId}`, {
    metrics,
    provider,
    model,
    project_id: projectId,
  })
  return response.data
}

export async function login(email, password) {
  const client = createClient()
  const response = await client.post('/auth/login', {
    email,
    password,
  })
  return response.data
}

export async function register(email, password) {
  const client = createClient()
  const response = await client.post('/auth/register', {
    email,
    password,
  })
  return response.data
}

export async function getCurrentUser({ accessToken, apiKey } = {}) {
  const client = createClient({ accessToken, apiKey })
  const response = await client.get('/auth/me')
  return response.data
}

export async function getProjects({ apiKey, accessToken } = {}) {
  const client = createClient({ apiKey, accessToken })
  const response = await client.get('/projects')
  return response.data
}

export async function createProject(name, { apiKey, accessToken } = {}) {
  const client = createClient({ apiKey, accessToken })
  const response = await client.post('/projects', { name })
  return response.data
}

export default {
  getTraces,
  getDatasets,
  createDataset,
  getDatasetSamples,
  createDatasetSample,
  createDatasetSamplesFromTraces,
  attachTracesToDataset,
  runEval,
  getEvalRuns,
  getProjectEvalRuns,
  getProjectEvalResults,
  getEvalRun,
  runBenchmark,
  getProjectDashboard,
  evaluateTrace,
  login,
  register,
  getCurrentUser,
  getProjects,
  createProject,
}
