import { useEffect, useState } from 'react'
import { getProjectDashboard } from '../api/client.js'

function readProjectId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('project_id') ||
    window.localStorage.getItem('activeProjectId') ||
    ''
  )
}

function DashboardCard({ label, value }) {
  return (
    <article className="dashboard-card">
      <div className="dashboard-card-label">{label}</div>
      <div className="dashboard-card-value">{value}</div>
    </article>
  )
}

export default function Dashboard() {
  const [projectId, setProjectId] = useState(() => readProjectId())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!projectId) {
      setData(null)
      setError('Set a project_id in the URL or in localStorage as activeProjectId.')
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')

    getProjectDashboard(projectId)
      .then((response) => {
        if (!cancelled) {
          setData(response?.data ?? response)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load dashboard.')
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
  }, [projectId])

  useEffect(() => {
    const syncProjectId = () => {
      setProjectId(window.localStorage.getItem('activeProjectId') || '')
    }

    window.addEventListener('activeprojectchange', syncProjectId)
    window.addEventListener('projectlistchange', syncProjectId)
    window.addEventListener('storage', syncProjectId)
    return () => {
      window.removeEventListener('activeprojectchange', syncProjectId)
      window.removeEventListener('projectlistchange', syncProjectId)
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

  return (
    <section className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h2>Dashboard</h2>
          <p>Project overview and evaluation health.</p>
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

      {loading ? <p>Loading dashboard...</p> : null}
      {error ? <p className="dashboard-error">{error}</p> : null}

      {data ? (
        <>
          <div className="dashboard-grid">
            <DashboardCard label="Total traces" value={data.total_traces} />
            <DashboardCard label="Total datasets" value={data.total_datasets} />
          </div>

          <section className="dashboard-scores">
            <h3>Average scores</h3>
            <div className="dashboard-grid">
              {Object.entries(data.avg_scores || {}).map(([metric, score]) => (
                <DashboardCard
                  key={metric}
                  label={metric}
                  value={Number(score).toFixed(3)}
                />
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  )
}
