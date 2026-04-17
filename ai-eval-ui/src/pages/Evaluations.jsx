import { useEffect, useState } from 'react'
import { getProjectEvalResults } from '../api/client.js'

function readProjectId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('project_id') ||
    window.localStorage.getItem('activeProjectId') ||
    ''
  )
}

function formatDate(value) {
  if (!value) {
    return '-'
  }

  return new Date(value).toLocaleString()
}

export default function Evaluations() {
  const [projectId, setProjectId] = useState(() => readProjectId())
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedRunId, setSelectedRunId] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('eval_run_id') || ''
  })

  useEffect(() => {
    if (!projectId) {
      setResults([])
      setError('Select a project to view its evaluation runs.')
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')

    getProjectEvalResults(projectId)
      .then((response) => {
        if (!cancelled) {
          const items = Array.isArray(response) ? response : response?.data ?? []
          setResults(
            selectedRunId
              ? items.filter((item) => item.eval_run_id === selectedRunId)
              : items,
          )
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load evaluation results.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [projectId, selectedRunId])

  useEffect(() => {
    const syncProjectContext = () => {
      setProjectId(window.localStorage.getItem('activeProjectId') || '')
      const params = new URLSearchParams(window.location.search)
      setSelectedRunId(params.get('eval_run_id') || '')
    }

    window.addEventListener('activeprojectchange', syncProjectContext)
    window.addEventListener('storage', syncProjectContext)
    return () => {
      window.removeEventListener('activeprojectchange', syncProjectContext)
      window.removeEventListener('storage', syncProjectContext)
    }
  }, [])

  useEffect(() => {
    if (projectId.trim()) {
      window.localStorage.setItem('activeProjectId', projectId.trim())
    } else {
      window.localStorage.removeItem('activeProjectId')
    }
  }, [projectId])

  return (
    <section className="dashboard-page evaluations-page">
      <header className="dashboard-header">
        <div>
          <h2>Evaluations</h2>
          <p>Review all evaluation results for the active project.</p>
          {selectedRunId ? (
            <p className="evaluation-result-link-text">
              Showing results for run <strong>{selectedRunId}</strong>.
            </p>
          ) : null}
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

      <div className="dashboard-grid">
        <article className="dashboard-card">
          <div className="dashboard-card-label">Total results</div>
          <div className="dashboard-card-value">{results.length}</div>
        </article>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Active project</div>
          <div className="dashboard-card-value">{projectId || '-'}</div>
        </article>
      </div>

      {loading ? <p>Loading evaluation runs...</p> : null}
      {error ? <p className="dashboard-error">{error}</p> : null}
      {!projectId ? (
        <article className="dashboard-card">
          <p>Select a project in the sidebar to view its evaluation history.</p>
        </article>
      ) : null}

      <div className="table-shell">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Dataset Id</th>
              <th>Run Id</th>
              <th>Metric</th>
              <th>Score</th>
              <th>Label</th>
              <th>Judge Model</th>
              <th>Created at</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr key={result.id}>
                <td className="table-cell-ellipsis">{result.id}</td>
                <td className="table-cell-ellipsis">{result.dataset_id}</td>
                <td className="table-cell-ellipsis">{result.eval_run_id}</td>
                <td>{result.metric_name}</td>
                <td>{Number(result.score || 0).toFixed(3)}</td>
                <td>{result.label}</td>
                <td>{result.judge_model}</td>
                <td>{formatDate(result.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
