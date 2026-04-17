import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api/client.js'

function AuthForm({ title, buttonLabel, onSubmit, helper }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const isRegistration = buttonLabel.toLowerCase() === 'register'

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!email.trim()) {
      setError('Email is required.')
      return
    }
    if (isRegistration && password.length < 8) {
      setError('Password must be at least 8 characters long.')
      return
    }
    if (!isRegistration && !password.trim()) {
      setError('Password is required.')
      return
    }
    setLoading(true)
    setError('')

    try {
      const response = await onSubmit(email, password)
      const payload = response?.data ?? response
      const data = payload?.data ?? payload
      if (data?.access_token) {
        window.localStorage.setItem('accessToken', data.access_token)
      }
      if (data?.user) {
        window.localStorage.setItem('activeUser', JSON.stringify(data.user))
      }
      navigate('/', { replace: true })
      window.location.reload()
    } catch (err) {
      setError(
        err?.response?.data?.error ||
          err?.response?.data?.detail ||
          err?.message ||
          'Authentication failed.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <article className="dashboard-card auth-card">
      <h3>{title}</h3>
      <p>{helper}</p>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>
          <span>Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            required
            minLength={isRegistration ? 8 : 1}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </label>
        {isRegistration ? (
          <p className="auth-hint">Password must be at least 8 characters long.</p>
        ) : null}
        {error ? <p className="dashboard-error">{error}</p> : null}
        <button type="submit" disabled={loading}>
          {loading ? 'Working...' : buttonLabel}
        </button>
      </form>
    </article>
  )
}

export function LoginPage() {
  return (
    <section className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h2>Login</h2>
          <p>Authenticate to load your projects and generate an active project context.</p>
        </div>
      </header>

      <div className="dashboard-grid auth-grid">
        <AuthForm
          title="Sign in"
          helper="Use your existing account to load projects from the backend."
          buttonLabel="Login"
          onSubmit={login}
        />
        <AuthForm
          title="Create account"
          helper="Register a new user if you are starting fresh."
          buttonLabel="Register"
          onSubmit={register}
        />
      </div>
    </section>
  )
}
