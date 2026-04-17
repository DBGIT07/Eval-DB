import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  attachTracesToDataset,
  createDataset,
  evaluateTrace,
  getDatasets,
  getTraces,
} from '../api/client.js'

function readProjectId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('project_id') ||
    window.localStorage.getItem('activeProjectId') ||
    ''
  )
}

export default function Traces() {
  const navigate = useNavigate()
  const [projectId, setProjectId] = useState(() => readProjectId())
  const [traces, setTraces] = useState([])
  const [datasets, setDatasets] = useState([])
  const [selectedTraceIds, setSelectedTraceIds] = useState([])
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [newDatasetName, setNewDatasetName] = useState('Selected traces dataset')
  const [newDatasetTaskType, setNewDatasetTaskType] = useState('chat')
  const [metricsInput, setMetricsInput] = useState('faithfulness,relevance,completeness,hallucination')
  const [providerInput, setProviderInput] = useState('mock')
  const [modelInput, setModelInput] = useState('mock')
  const [loading, setLoading] = useState(false)
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [actionLoadingId, setActionLoadingId] = useState('')
  const [resultLinks, setResultLinks] = useState({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const selectedCount = selectedTraceIds.length
  const allSelected = traces.length > 0 && selectedCount === traces.length
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) || null,
    [datasets, selectedDatasetId],
  )

  const parseMetrics = () =>
    metricsInput
      .split(',')
      .map((metric) => metric.trim())
      .filter(Boolean)

  const extractErrorMessage = (err, fallback) => {
    if (err && typeof err === 'object') {
      const responseMessage =
        err.response?.data?.detail ||
        err.response?.data?.error ||
        err.response?.data?.message
      if (typeof responseMessage === 'string' && responseMessage.trim()) {
        return responseMessage
      }
    }

    if (err instanceof Error && err.message) {
      return err.message
    }

    return fallback
  }

  useEffect(() => {
    if (!projectId) {
      setTraces([])
      setDatasets([])
      setSelectedTraceIds([])
      setSelectedDatasetId('')
      setResultLinks({})
      setError('Set a project_id in the URL or in localStorage as activeProjectId.')
      return
    }

    let cancelled = false
    setLoading(true)
    setDatasetsLoading(true)
    setError('')
    setMessage('')

    getTraces({ projectId })
      .then((response) => {
        if (!cancelled) {
          setTraces(Array.isArray(response) ? response : response?.data ?? [])
          setResultLinks({})
          setSelectedTraceIds([])
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load traces.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    getDatasets({ projectId })
      .then((response) => {
        if (!cancelled) {
          const items = Array.isArray(response) ? response : response?.data ?? []
          setDatasets(items)
          const nextSelected = items.some((dataset) => dataset.id === selectedDatasetId)
            ? selectedDatasetId
            : items[0]?.id || ''
          setSelectedDatasetId(nextSelected)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load datasets.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDatasetsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [projectId])

  useEffect(() => {
    const syncProjectId = () => {
      setProjectId(window.localStorage.getItem('activeProjectId') || '')
    }

    window.addEventListener('activeprojectchange', syncProjectId)
    window.addEventListener('storage', syncProjectId)
    return () => {
      window.removeEventListener('activeprojectchange', syncProjectId)
      window.removeEventListener('storage', syncProjectId)
    }
  }, [])

  useEffect(() => {
    if (projectId.trim()) {
      window.localStorage.setItem('activeProjectId', projectId.trim())
    } else {
      window.localStorage.removeItem('activeProjectId')
    }
  }, [projectId])

  const handleToggleTrace = (traceId) => {
    setSelectedTraceIds((current) =>
      current.includes(traceId)
        ? current.filter((id) => id !== traceId)
        : [...current, traceId],
    )
  }

  const handleToggleAll = () => {
    setSelectedTraceIds((current) => (allSelected ? [] : traces.map((trace) => trace.id)))
  }

  const reloadDatasets = async () => {
    if (!projectId) {
      return
    }

    const response = await getDatasets({ projectId })
    const items = Array.isArray(response) ? response : response?.data ?? []
    setDatasets(items)
    setSelectedDatasetId((current) =>
      items.some((dataset) => dataset.id === current) ? current : items[0]?.id || '',
    )
  }

  const handleAttachSelectedToExisting = async () => {
    if (selectedTraceIds.length === 0) {
      setError('Please select at least one trace.')
      return
    }
    if (!selectedDatasetId) {
      setError('Please choose a dataset.')
      return
    }

    setBulkLoading(true)
    setError('')
    setMessage('')

    try {
      await attachTracesToDataset(selectedDatasetId, selectedTraceIds)
      setMessage(`Attached ${selectedTraceIds.length} trace(s) to ${selectedDataset?.name || 'the dataset'}.`)
      setSelectedTraceIds([])
      await reloadDatasets()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to attach traces.')
    } finally {
      setBulkLoading(false)
    }
  }

  const handleCreateNewDataset = async () => {
    if (selectedTraceIds.length === 0) {
      setError('Please select at least one trace.')
      return
    }
    if (!newDatasetName.trim() || !newDatasetTaskType.trim()) {
      setError('Please provide both a dataset name and task type.')
      return
    }

    setBulkLoading(true)
    setError('')
    setMessage('')

    try {
      const response = await createDataset(
        {
          name: newDatasetName.trim(),
          taskType: newDatasetTaskType.trim(),
          projectId,
        },
      )
      const created = response?.data ?? response
      await attachTracesToDataset(created.id, selectedTraceIds)
      setMessage(`Created ${created.name} and attached ${selectedTraceIds.length} trace(s).`)
      setSelectedTraceIds([])
      await reloadDatasets()
      setSelectedDatasetId(created.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create dataset and attach traces.')
    } finally {
      setBulkLoading(false)
    }
  }

  const handleEvaluate = async (traceId) => {
    setActionLoadingId(traceId)
    setError('')
    setMessage('')

    const metrics = parseMetrics()
    if (metrics.length === 0) {
      setError('Please enter at least one metric.')
      setActionLoadingId('')
      return
    }

    try {
      const response = await evaluateTrace(traceId, {
        metrics,
        provider: providerInput.trim() || 'mock',
        model: modelInput.trim() || 'mock',
        projectId,
      })
      const evalRunId = response?.eval_run_id || response?.data?.eval_run_id || ''
      if (evalRunId) {
        const resultUrl = `/evals?project_id=${encodeURIComponent(projectId)}&eval_run_id=${encodeURIComponent(evalRunId)}`
        setResultLinks((current) => ({
          ...current,
          [traceId]: resultUrl,
        }))
        setMessage(`Evaluation completed for trace ${traceId}. View the result link in the table.`)
        navigate(resultUrl)
      } else {
        setMessage(`Evaluation started for trace ${traceId}.`)
      }
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to evaluate trace.'))
    } finally {
      setActionLoadingId('')
    }
  }

  return (
    <section className="dashboard-page traces-page">
      <header className="dashboard-header">
        <div>
          <h2>Traces</h2>
          <p>Review recent traces, evaluate them, and turn selected traces into datasets.</p>
        </div>
        <label className="dashboard-project-field">
          <span>Project ID</span>
          <input
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            placeholder="project_123"
          />
        </label>
      </header>

      <article className="dashboard-card traces-bulk-card">
        <div className="traces-bulk-topline">
          <div>
            <h3>Bulk Actions</h3>
            <p>{selectedCount} trace(s) selected.</p>
          </div>
          <label className="traces-select-all">
            <input type="checkbox" checked={allSelected} onChange={handleToggleAll} />
            Select all
          </label>
        </div>

        <div className="traces-bulk-grid">
          <label>
            <span>Existing dataset</span>
            <select
              value={selectedDatasetId}
              onChange={(event) => setSelectedDatasetId(event.target.value)}
              disabled={datasetsLoading}
            >
              <option value="">{datasetsLoading ? 'Loading datasets...' : 'Choose a dataset'}</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} ({dataset.task_type})
                </option>
              ))}
            </select>
          </label>

          <div className="traces-bulk-buttons">
            <button type="button" onClick={handleAttachSelectedToExisting} disabled={bulkLoading}>
              Add to Existing
            </button>
          </div>

          <label>
            <span>New dataset name</span>
            <input
              value={newDatasetName}
              onChange={(event) => setNewDatasetName(event.target.value)}
              placeholder="Selected traces dataset"
            />
          </label>

          <label>
            <span>Task type</span>
            <input
              value={newDatasetTaskType}
              onChange={(event) => setNewDatasetTaskType(event.target.value)}
              placeholder="chat"
            />
          </label>

          <div className="traces-bulk-buttons">
            <button type="button" onClick={handleCreateNewDataset} disabled={bulkLoading}>
              Create New Dataset
            </button>
          </div>

          <label className="traces-eval-field">
            <span>Metrics</span>
            <input
              value={metricsInput}
              onChange={(event) => setMetricsInput(event.target.value)}
              placeholder="faithfulness,relevance,hallucination"
            />
          </label>

          <label>
            <span>Provider</span>
            <input
              value={providerInput}
              onChange={(event) => setProviderInput(event.target.value)}
              placeholder="mock"
            />
          </label>

          <label>
            <span>Model</span>
            <input
              value={modelInput}
              onChange={(event) => setModelInput(event.target.value)}
              placeholder="mock"
            />
          </label>
        </div>
      </article>

      {loading ? <p>Loading traces...</p> : null}
      {error ? <p className="dashboard-error">{error}</p> : null}
      {message ? <p>{message}</p> : null}

      <div className="table-shell">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Select</th>
              <th>Id</th>
              <th>Prompt</th>
              <th>Response</th>
              <th>Model</th>
              <th>Latency</th>
              <th>Created at</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {traces.map((trace) => (
              <tr key={trace.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedTraceIds.includes(trace.id)}
                    onChange={() => handleToggleTrace(trace.id)}
                  />
                </td>
                <td className="table-cell-ellipsis">{trace.id}</td>
                <td className="table-cell-ellipsis">{trace.prompt}</td>
                <td className="table-cell-ellipsis">{trace.response}</td>
                <td>{trace.model}</td>
                <td>{trace.latency_ms ?? '-'}</td>
                <td>{trace.created_at ? new Date(trace.created_at).toLocaleString() : '-'}</td>
                <td>
                  <div className="evaluation-actions">
                    <button
                      type="button"
                      onClick={() => handleEvaluate(trace.id)}
                      disabled={actionLoadingId === trace.id}
                    >
                      {actionLoadingId === trace.id ? 'Evaluating...' : 'Evaluate'}
                    </button>
                    {resultLinks[trace.id] ? (
                      <a className="evaluation-result-link" href={resultLinks[trace.id]}>
                        View result
                      </a>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
