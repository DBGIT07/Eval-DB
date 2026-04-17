import { useEffect, useMemo, useState } from 'react'
import { runBenchmark } from '../api/client.js'

function readProjectId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('project_id') ||
    window.localStorage.getItem('activeProjectId') ||
    ''
  )
}

function readDatasetId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('dataset_id') ||
    window.localStorage.getItem('activeDatasetId') ||
    ''
  )
}

function formatMetric(value) {
  if (value === null || value === undefined || value === '') {
    return '-'
  }

  const number = Number(value)
  if (Number.isNaN(number)) {
    return '-'
  }

  return number.toFixed(2)
}

function VariantRow({ variant, index, onChange, onRemove, canRemove }) {
  return (
    <div className="benchmark-variant-row">
      <label>
        <span>Name</span>
        <input
          value={variant.name}
          onChange={(event) => onChange(index, 'name', event.target.value)}
          placeholder={`Variant ${index + 1}`}
        />
      </label>
      <label>
        <span>Provider</span>
        <input
          value={variant.provider}
          onChange={(event) => onChange(index, 'provider', event.target.value)}
          placeholder="mock"
        />
      </label>
      <label>
        <span>Model</span>
        <input
          value={variant.model}
          onChange={(event) => onChange(index, 'model', event.target.value)}
          placeholder="gpt-4o-mini"
        />
      </label>
      <button type="button" onClick={() => onRemove(index)} disabled={!canRemove}>
        Remove
      </button>
    </div>
  )
}

function ResultTable({ results, winner }) {
  const rows = useMemo(() => Object.entries(results || {}), [results])

  if (!rows.length) {
    return (
      <article className="dashboard-card">
        <h3>Comparison results</h3>
        <p>Run a benchmark to compare variants.</p>
      </article>
    )
  }

  return (
    <article className="dashboard-card benchmark-results-card">
      <h3>Comparison results</h3>
      <div className="table-shell">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Variant</th>
              <th>Faithfulness</th>
              <th>Groundedness</th>
              <th>Precision</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([variantName, scores]) => {
              const isWinner = winner === variantName
              return (
                <tr key={variantName} className={isWinner ? 'is-selected' : ''}>
                  <td>
                    <strong>{variantName}</strong>
                    {isWinner ? <span className="benchmark-winner-badge">Best</span> : null}
                  </td>
                  <td>{formatMetric(scores.faithfulness)}</td>
                  <td>{formatMetric(scores.groundedness)}</td>
                  <td>{formatMetric(scores.context_precision ?? scores.precision)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </article>
  )
}

export default function Benchmark() {
  const [projectId, setProjectId] = useState(() => readProjectId())
  const [datasetId, setDatasetId] = useState(() => readDatasetId())
  const [variants, setVariants] = useState([
    { name: 'baseline', provider: 'mock', model: 'mock' },
    { name: 'candidate', provider: 'mock', model: 'mock' },
  ])
  const [results, setResults] = useState({})
  const [winner, setWinner] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const metrics = ['faithfulness', 'groundedness', 'context_precision']

  const canRun = projectId.trim() && datasetId.trim() && variants.some((variant) => variant.name.trim())

  const updateVariant = (index, field, value) => {
    setVariants((current) =>
      current.map((variant, idx) => (idx === index ? { ...variant, [field]: value } : variant)),
    )
  }

  const addVariant = () => {
    setVariants((current) => [...current, { name: '', provider: 'mock', model: 'mock' }])
  }

  const removeVariant = (index) => {
    setVariants((current) => current.filter((_, idx) => idx !== index))
  }

  const handleRun = async (event) => {
    event.preventDefault()
    setError('')
    setMessage('')
    setLoading(true)

    try {
      const cleanedVariants = variants
        .map((variant) => ({
          name: variant.name.trim(),
          provider: variant.provider.trim() || 'mock',
          model: variant.model.trim() || 'mock',
        }))
        .filter((variant) => variant.name)

      const response = await runBenchmark(datasetId.trim(), {
        variants: cleanedVariants,
        metrics,
        projectId: projectId.trim(),
      })

      setResults(response?.variants || {})
      setWinner(response?.winner || '')
      setMessage('Benchmark completed successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run benchmark.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const syncProjectContext = () => {
      setProjectId(window.localStorage.getItem('activeProjectId') || '')
      setDatasetId(window.localStorage.getItem('activeDatasetId') || '')
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

  useEffect(() => {
    if (datasetId.trim()) {
      window.localStorage.setItem('activeDatasetId', datasetId.trim())
    } else {
      window.localStorage.removeItem('activeDatasetId')
    }
  }, [datasetId])

  return (
    <section className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h2>Benchmark</h2>
          <p>Compare multiple variants on the same dataset.</p>
        </div>
        <div className="evaluation-header-fields">
          <label className="dashboard-project-field">
            <span>Project ID</span>
            <input
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              placeholder="project_123"
            />
          </label>
          <label className="dashboard-project-field">
            <span>Dataset ID</span>
            <input
              value={datasetId}
              onChange={(event) => setDatasetId(event.target.value)}
              placeholder="dataset_123"
            />
          </label>
        </div>
      </header>

      <article className="dashboard-card">
        <div className="dashboard-card-label">Variants</div>
        <div className="benchmark-variant-list">
          {variants.map((variant, index) => (
            <VariantRow
              key={`${variant.name || 'variant'}-${index}`}
              variant={variant}
              index={index}
              onChange={updateVariant}
              onRemove={removeVariant}
              canRemove={variants.length > 1}
            />
          ))}
        </div>
        <div className="benchmark-actions">
          <button type="button" onClick={addVariant}>
            Add variant
          </button>
          <button type="button" onClick={handleRun} disabled={!canRun || loading}>
            {loading ? 'Running...' : 'Run benchmark'}
          </button>
        </div>
      </article>

      {error ? <p className="dashboard-error">{error}</p> : null}
      {message ? <p>{message}</p> : null}

      <ResultTable results={results} winner={winner} />
    </section>
  )
}
