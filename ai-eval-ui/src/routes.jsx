import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout.jsx'
import DashboardPage from './pages/Dashboard.jsx'
import BenchmarkPage from './pages/Benchmark.jsx'
import DatasetsPage from './pages/Datasets.jsx'
import EvaluationsPage from './pages/Evaluations.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { ProjectsPage } from './pages/ProjectsPage.jsx'
import TracesPage from './pages/Traces.jsx'

function hasAccessToken() {
  return Boolean(window.localStorage.getItem('accessToken'))
}

function RequireAuth() {
  const location = useLocation()
  if (!hasAccessToken()) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}

function PublicOnly() {
  if (hasAccessToken()) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}

export const router = createBrowserRouter([
  {
    element: <PublicOnly />,
    children: [{ path: '/login', element: <LoginPage /> }],
  },
  {
    element: <RequireAuth />,
    children: [
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
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
