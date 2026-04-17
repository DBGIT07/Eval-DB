import { useEffect, useMemo, useState } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { getCurrentUser } from './api/client.js'
import { AppLayout } from './layout/AppLayout.jsx'
import BenchmarkPage from './pages/Benchmark.jsx'
import DashboardPage from './pages/Dashboard.jsx'
import DatasetsPage from './pages/Datasets.jsx'
import EvaluationsPage from './pages/Evaluations.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { ProjectsPage } from './pages/ProjectsPage.jsx'
import TracesPage from './pages/Traces.jsx'

function buildPublicRouter() {
  return createBrowserRouter([
    { path: '/login', element: <LoginPage /> },
    { path: '*', element: <Navigate to="/login" replace /> },
  ])
}

function buildAppRouter() {
  return createBrowserRouter([
    {
      element: <AppLayout />,
      children: [
        { path: '/', element: <DashboardPage /> },
        { path: '/datasets', element: <DatasetsPage /> },
        { path: '/benchmark', element: <BenchmarkPage /> },
        { path: '/evals', element: <EvaluationsPage /> },
        { path: '/evaluations', element: <EvaluationsPage /> },
        { path: '/traces', element: <TracesPage /> },
        { path: '/projects', element: <ProjectsPage /> },
        { path: '/login', element: <Navigate to="/" replace /> },
      ],
    },
    { path: '*', element: <Navigate to="/" replace /> },
  ])
}

export default function App() {
  const [authState, setAuthState] = useState('checking')

  useEffect(() => {
    const accessToken = window.localStorage.getItem('accessToken') || ''
    if (!accessToken) {
      setAuthState('guest')
      return
    }

    let cancelled = false
    getCurrentUser({ accessToken })
      .then((user) => {
        if (cancelled) {
          return
        }
        window.localStorage.setItem('activeUser', JSON.stringify(user))
        setAuthState('authenticated')
      })
      .catch(() => {
        if (cancelled) {
          return
        }
        window.localStorage.removeItem('accessToken')
        window.localStorage.removeItem('activeUser')
        window.localStorage.removeItem('activeProjectId')
        window.localStorage.removeItem('activeDatasetId')
        setAuthState('guest')
      })

    return () => {
      cancelled = true
    }
  }, [])

  const router = useMemo(
    () => (authState === 'authenticated' ? buildAppRouter() : buildPublicRouter()),
    [authState],
  )

  if (authState === 'checking') {
    return (
      <div className="auth-loading">
        <h1>Eval Studio</h1>
        <p>Checking your session...</p>
      </div>
    )
  }

  return <RouterProvider router={router} />
}
