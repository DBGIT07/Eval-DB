import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { getProjects } from '../api/client.js'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/traces', label: 'Traces' },
  { to: '/datasets', label: 'Datasets' },
  { to: '/evals', label: 'Evaluations' },
  { to: '/benchmark', label: 'Benchmark' },
  { to: '/projects', label: 'Projects' },
]

export function Sidebar() {
  const [projects, setProjects] = useState([])
  const [activeProjectId, setActiveProjectId] = useState(() =>
    window.localStorage.getItem('activeProjectId') || '',
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const syncProjects = () => {
      const accessToken = window.localStorage.getItem('accessToken') || ''
      if (!accessToken) {
        setProjects([])
        setLoading(false)
        return
      }

      let cancelled = false
      setLoading(true)
      setError('')

      getProjects()
        .then((response) => {
          if (cancelled) {
            return
          }

          const items = Array.isArray(response) ? response : response?.data ?? []
          setProjects(items)

          const stored = window.localStorage.getItem('activeProjectId') || ''
          const current = items.some((project) => project.id === stored)
            ? stored
            : items[0]?.id || ''

          if (current) {
            window.localStorage.setItem('activeProjectId', current)
            setActiveProjectId(current)
            window.dispatchEvent(new Event('activeprojectchange'))
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : 'Sign in to load projects.')
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
    }

    syncProjects()
    window.addEventListener('projectlistchange', syncProjects)
    return () => {
      window.removeEventListener('projectlistchange', syncProjects)
    }
  }, [])

  const handleSelectProject = (projectId) => {
    window.localStorage.setItem('activeProjectId', projectId)
    window.localStorage.removeItem('activeDatasetId')
    setActiveProjectId(projectId)
    window.dispatchEvent(new Event('activeprojectchange'))
  }

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar-brand">
        <h1>Eval Studio</h1>
        <p>Project-scoped RAG evaluation and alerts.</p>
      </div>

      <nav className="app-sidebar-nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <section className="app-sidebar-projects">
        <div className="app-sidebar-section-title">Active project</div>
        <label className="app-sidebar-project-select">
          <span>Choose project</span>
          <select
            value={activeProjectId}
            onChange={(event) => handleSelectProject(event.target.value)}
            disabled={loading || projects.length === 0}
          >
            <option value="">{loading ? 'Loading projects...' : 'Select a project'}</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <div className="app-sidebar-current-project">
          {activeProjectId || 'No project selected'}
        </div>
        {loading ? <p className="app-sidebar-note">Loading projects...</p> : null}
        {error ? <p className="app-sidebar-note">{error}</p> : null}
        {projects.length > 0 ? (
          <div className="app-sidebar-project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={project.id === activeProjectId ? 'active' : ''}
                onClick={() => handleSelectProject(project.id)}
              >
                <span>{project.name}</span>
                <small>{project.id}</small>
              </button>
            ))}
          </div>
        ) : (
          <p className="app-sidebar-note">
            Create a project from the Projects page, then select it here.
          </p>
        )}
      </section>
    </aside>
  )
}

export default Sidebar
