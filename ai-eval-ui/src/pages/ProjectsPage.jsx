import { useEffect, useState } from 'react'
import { createProject, getProjects } from '../api/client.js'

function readActiveProjectId() {
  return window.localStorage.getItem('activeProjectId') || ''
}

export function ProjectsPage() {
  const [projects, setProjects] = useState([])
  const [activeProjectId, setActiveProjectId] = useState(() => readActiveProjectId())
  const [projectName, setProjectName] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const loadProjects = () => {
    const accessToken = window.localStorage.getItem('accessToken') || ''
    if (!accessToken) {
      setProjects([])
      setLoading(false)
      setError('Log in to view and create projects.')
      return
    }

    setLoading(true)
    setError('')

    getProjects()
      .then((response) => {
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
        window.dispatchEvent(new Event('projectlistchange'))
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load projects.')
      })
      .finally(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    loadProjects()
  }, [])

  const handleCreate = async (event) => {
    event.preventDefault()
    if (!window.localStorage.getItem('accessToken')) {
      setError('Log in to create a project.')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')

    try {
      await createProject(projectName.trim())
      setProjectName('')
      setMessage('Project created successfully.')
      loadProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project.')
    } finally {
      setSaving(false)
    }
  }

  const handleSelect = (projectId) => {
    window.localStorage.setItem('activeProjectId', projectId)
    window.localStorage.removeItem('activeDatasetId')
    setActiveProjectId(projectId)
    setMessage('Active project updated.')
    window.dispatchEvent(new Event('activeprojectchange'))
    window.dispatchEvent(new Event('projectlistchange'))
  }

  return (
    <section className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h2>Projects</h2>
          <p>Create, browse, and manage projects.</p>
        </div>
        <label className="dashboard-project-field">
          <span>Active project</span>
          <input value={activeProjectId} readOnly placeholder="Select a project" />
        </label>
      </header>

      <div className="dashboard-grid">
        <article className="dashboard-card">
          <div className="dashboard-card-label">Total projects</div>
          <div className="dashboard-card-value">{projects.length}</div>
        </article>
      </div>

      <article className="dashboard-card">
        <h3>Create project</h3>
        <form className="auth-form" onSubmit={handleCreate}>
          <label>
            <span>Name</span>
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="Acme Support"
            />
          </label>
          <button type="submit" disabled={saving || !projectName.trim()}>
            {saving ? 'Creating...' : 'Create project'}
          </button>
        </form>
      </article>

      {loading ? <p>Loading projects...</p> : null}
      {error ? <p className="dashboard-error">{error}</p> : null}
      {message ? <p>{message}</p> : null}

      <div className="table-shell">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Project ID</th>
              <th>Created at</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr key={project.id} className={project.id === activeProjectId ? 'is-selected' : ''}>
                <td>{project.name}</td>
                <td className="table-cell-ellipsis">{project.id}</td>
                <td>{project.created_at ? new Date(project.created_at).toLocaleString() : '-'}</td>
                <td>
                  <button type="button" onClick={() => handleSelect(project.id)}>
                    Select
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
