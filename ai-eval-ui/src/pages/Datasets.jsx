import { useEffect, useState } from 'react'
import {
  createDataset,
  createDatasetSample,
  createDatasetSamplesFromTraces,
  getDatasets,
  getDatasetSamples,
  getTraces,
  runEval,
} from '../api/client.js'

const METRIC_OPTIONS = [
  'faithfulness',
  'relevance',
  'completeness',
  'groundedness',
  'context_precision',
  'context_recall',
  'hallucination',
]

function readProjectId() {
  const params = new URLSearchParams(window.location.search)
  return (
    params.get('project_id') ||
    window.localStorage.getItem('activeProjectId') ||
    ''
  )
}

export default function Datasets() {
  const [projectId, setProjectId] = useState(() => readProjectId())
  const [datasets, setDatasets] = useState([])
  const [traces, setTraces] = useState([])
  const [loading, setLoading] = useState(false)
  const [tracesLoading, setTracesLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [samplesViewDialog, setSamplesViewDialog] = useState({
    open: false,
    datasetId: '',
    datasetName: '',
    loading: false,
    samples: [],
  })
  const [samplesDialog, setSamplesDialog] = useState({
    open: false,
    datasetId: '',
    datasetName: '',
    mode: 'traces',
    selectedTraceIds: [],
    jsonText: '{\n  "data": {\n    "query": "Where is my order?",\n    "answer": "Your order was shipped yesterday.",\n    "sources": [\n      "Order shipped yesterday"\n    ],\n    "metadata": {\n      "priority": "high",\n      "channel": "support"\n    }\n  }\n}',
    chatInput: '',
    chatContext: 'Order shipped yesterday',
    chatExpectedOutput: 'Your order was shipped yesterday.',
    submitLoading: false,
    resultText: '',
  })
  const [evalDialog, setEvalDialog] = useState({
    open: false,
    datasetId: '',
    datasetName: '',
    metrics: ['faithfulness', 'relevance', 'completeness', 'hallucination'],
    provider: 'openai',
    model: 'gpt-4o-mini',
  })
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalResult, setEvalResult] = useState(null)
  const [form, setForm] = useState({
    name: '',
    taskType: 'chat',
  })

  useEffect(() => {
    if (!projectId) {
      setDatasets([])
      setError('Set a project_id in the URL or in localStorage as activeProjectId.')
      return
    }

    let cancelled = false
    setLoading(true)
    setTracesLoading(true)
    setError('')
    setMessage('')

    getDatasets({ projectId })
      .then((response) => {
        if (!cancelled) {
          const payload = response?.data ?? response
          setDatasets(Array.isArray(payload) ? payload : [])
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load datasets.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    getTraces({ projectId })
      .then((response) => {
        if (!cancelled) {
          const payload = response?.data ?? response
          setTraces(Array.isArray(payload) ? payload : [])
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load traces.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTracesLoading(false)
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

  const handleCreate = async (event) => {
    event.preventDefault()
    setError('')
    setMessage('')

    try {
      const response = await createDataset({
        name: form.name,
        taskType: form.taskType,
        projectId,
      })
      const created = response?.data ?? response
      setDatasets((current) => [created, ...current])
      setForm({ name: '', taskType: 'chat' })
      setMessage('Dataset created successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create dataset.')
    }
  }

  const openSamplesDialog = (datasetId) => {
    const selected = datasets.find((dataset) => dataset.id === datasetId)
    setError('')
    setMessage('')
    setSamplesDialog((current) => ({
      ...current,
      open: true,
      datasetId,
      datasetName: selected?.name || datasetId,
      selectedTraceIds: [],
      resultText: '',
    }))
  }

  const openViewSamplesDialog = async (datasetId) => {
    const selected = datasets.find((dataset) => dataset.id === datasetId)
    setError('')
    setMessage('')
    setSamplesViewDialog((current) => ({
      ...current,
      open: true,
      datasetId,
      datasetName: selected?.name || datasetId,
      loading: true,
      samples: [],
    }))

    try {
      const response = await getDatasetSamples(datasetId)
      const payload = response?.data ?? response
      setSamplesViewDialog((current) => ({
        ...current,
        loading: false,
        samples: Array.isArray(payload) ? payload : [],
      }))
    } catch (err) {
      setSamplesViewDialog((current) => ({
        ...current,
        loading: false,
      }))
      setError(err instanceof Error ? err.message : 'Failed to load samples.')
    }
  }

  const closeViewSamplesDialog = () => {
    setSamplesViewDialog((current) => ({
      ...current,
      open: false,
      loading: false,
      samples: [],
    }))
  }

  const closeSamplesDialog = () => {
    setSamplesDialog((current) => ({
      ...current,
      open: false,
      submitLoading: false,
      resultText: '',
      selectedTraceIds: [],
    }))
  }

  const toggleTraceSelection = (traceId) => {
    setSamplesDialog((current) => {
      const selectedTraceIds = current.selectedTraceIds.includes(traceId)
        ? current.selectedTraceIds.filter((id) => id !== traceId)
        : [...current.selectedTraceIds, traceId]
      return { ...current, selectedTraceIds }
    })
  }

  const toggleAllTraces = () => {
    setSamplesDialog((current) => {
      const allSelected = traces.length > 0 && current.selectedTraceIds.length === traces.length
      return {
        ...current,
        selectedTraceIds: allSelected ? [] : traces.map((trace) => trace.id),
      }
    })
  }

  const handleSubmitSamplesDialog = async (event) => {
    event.preventDefault()
    setError('')
    setMessage('')

    try {
      setSamplesDialog((current) => ({ ...current, submitLoading: true, resultText: '' }))

      if (samplesDialog.mode === 'traces') {
        if (samplesDialog.selectedTraceIds.length === 0) {
          throw new Error('Please select at least one trace.')
        }
        const response = await createDatasetSamplesFromTraces(
          samplesDialog.datasetId,
          samplesDialog.selectedTraceIds,
        )
        const createdSamples = response?.data ?? response
        setSamplesDialog((current) => ({
          ...current,
          resultText: `Added ${Array.isArray(createdSamples) ? createdSamples.length : samplesDialog.selectedTraceIds.length} sample(s) from traces.`,
        }))
        setMessage(`Added ${samplesDialog.selectedTraceIds.length} trace-based sample(s) to ${samplesDialog.datasetName}.`)
        return
      }

      if (samplesDialog.mode === 'json') {
        let parsed
        try {
          parsed = JSON.parse(samplesDialog.jsonText)
        } catch {
          throw new Error('Please enter valid JSON.')
        }
        const response = await createDatasetSample(samplesDialog.datasetId, parsed)
        const createdSample = response?.data ?? response
        setSamplesDialog((current) => ({
          ...current,
          resultText: `Created sample ${createdSample.id}.`,
        }))
        setMessage(`Added JSON sample to ${samplesDialog.datasetName}.`)
        return
      }

      const context = samplesDialog.chatContext
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)

      const payload = {
        input: samplesDialog.chatInput.trim(),
        context,
        expected_output: samplesDialog.chatExpectedOutput.trim(),
      }

      const response = await createDatasetSample(samplesDialog.datasetId, payload)
      const createdSample = response?.data ?? response
      setSamplesDialog((current) => ({
        ...current,
        resultText: `Created sample ${createdSample.id}.`,
      }))
      setMessage(`Added chat sample to ${samplesDialog.datasetName}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add samples.')
    } finally {
      setSamplesDialog((current) => ({ ...current, submitLoading: false }))
    }
  }

  const handleRunEvaluation = async (datasetId) => {
    const selected = datasets.find((dataset) => dataset.id === datasetId)
    setError('')
    setMessage('')
    setEvalResult(null)
    setEvalDialog((current) => ({
      ...current,
      open: true,
      datasetId,
      datasetName: selected?.name || datasetId,
    }))
  }

  const closeEvalDialog = () => {
    setEvalLoading(false)
    setEvalResult(null)
    setEvalDialog((current) => ({ ...current, open: false }))
  }

  const handleSubmitEvalDialog = async (event) => {
    event.preventDefault()
    setError('')
    setMessage('')
    setEvalResult(null)

    if (evalDialog.metrics.length === 0) {
      setError('Please select at least one metric.')
      return
    }

    try {
      setEvalLoading(true)
      const response = await runEval(evalDialog.datasetId, {
        metrics: evalDialog.metrics,
        provider: evalDialog.provider.trim(),
        model: evalDialog.model.trim(),
        projectId,
      })
      const result = response?.data ?? response
      setMessage(
        result?.queued
          ? `Evaluation queued successfully for ${evalDialog.datasetName}.`
          : `Evaluation started successfully for ${evalDialog.datasetName}.`,
      )
      setEvalResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run evaluation.')
    } finally {
      setEvalLoading(false)
    }
  }

  return (
    <section className="dashboard-page datasets-page">
      <header className="dashboard-header">
        <div>
          <h2>Datasets</h2>
          <p>Manage datasets and run evaluations.</p>
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

      <section className="dataset-create-card dashboard-card">
        <h3>Add Dataset</h3>
        <form id="create-dataset-form" className="dataset-create-form" onSubmit={handleCreate}>
          <label>
            <span>Name</span>
            <input
              type="text"
              name="name"
              placeholder="Customer support traces"
              required
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label>
            <span>Task Type</span>
            <input
              type="text"
              name="task_type"
              placeholder="chat"
              required
              value={form.taskType}
              onChange={(event) => setForm((current) => ({ ...current, taskType: event.target.value }))}
            />
          </label>
          <button type="submit">Create Dataset</button>
        </form>
      </section>

      <section className="dataset-example-card dashboard-card">
        <h3>Dataset Sample API Example</h3>
        <p className="dataset-example-copy">
          <code>POST /dataset/{'{dataset_id}'}/samples</code> accepts either structured fields or a full JSON payload in <code>data</code>.
        </p>
        <pre className="dataset-example-code">{`{
  "data": {
    "query": "Where is my order?",
    "answer": "Your order was shipped yesterday.",
    "sources": [
      "Order shipped yesterday"
    ],
    "metadata": {
      "priority": "high",
      "channel": "support"
    }
  }
}`}</pre>
        <p className="dataset-example-copy dataset-example-copy-bottom">
          You can still send the legacy shape too:
        </p>
        <pre className="dataset-example-code">{`{
  "input": "Where is my order?",
  "context": ["Order shipped yesterday"],
  "expected_output": "Your order was shipped yesterday."
}`}</pre>
      </section>

      {loading ? <p>Loading datasets...</p> : null}
      {error ? <p className="dashboard-error">{error}</p> : null}
      {message ? <p>{message}</p> : null}

      <div className="table-shell">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Name</th>
              <th>Task type</th>
              <th>Created at</th>
              <th>Add samples</th>
              <th>View samples</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => (
              <tr key={dataset.id}>
                <td className="table-cell-ellipsis">{dataset.id}</td>
                <td>{dataset.name}</td>
                <td>{dataset.task_type}</td>
                <td>{dataset.created_at ? new Date(dataset.created_at).toLocaleString() : '-'}</td>
                <td>
                  <button type="button" onClick={() => openSamplesDialog(dataset.id)}>
                    Add samples
                  </button>
                </td>
                <td>
                  <button type="button" onClick={() => openViewSamplesDialog(dataset.id)}>
                    View samples
                  </button>
                </td>
                <td>
                  <button type="button" onClick={() => handleRunEvaluation(dataset.id)}>
                    Run Evaluation
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {evalDialog.open ? (
        <div className="modal-backdrop" role="presentation" onClick={closeEvalDialog}>
          <div
            className="modal-card dashboard-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="run-eval-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 id="run-eval-title">Run Evaluation</h3>
                <p>Dataset: {evalDialog.datasetName}</p>
              </div>
              <button type="button" className="modal-close-button" onClick={closeEvalDialog}>
                Close
              </button>
            </div>

            <form className="modal-form" onSubmit={handleSubmitEvalDialog}>
              <label>
                <span>Metrics</span>
                <select
                  multiple
                  value={evalDialog.metrics}
                  onChange={(event) => {
                    const values = Array.from(event.target.selectedOptions).map((option) => option.value)
                    setEvalDialog((current) => ({ ...current, metrics: values }))
                  }}
                >
                  {METRIC_OPTIONS.map((metric) => (
                    <option key={metric} value={metric}>
                      {metric}
                    </option>
                  ))}
                </select>
                <small>Hold Ctrl or Cmd to select multiple metrics.</small>
              </label>

              <label>
                <span>Provider</span>
                <input
                  value={evalDialog.provider}
                  onChange={(event) => setEvalDialog((current) => ({ ...current, provider: event.target.value }))}
                  placeholder="openai"
                />
              </label>

              <label>
                <span>Model</span>
                <input
                  value={evalDialog.model}
                  onChange={(event) => setEvalDialog((current) => ({ ...current, model: event.target.value }))}
                  placeholder="gpt-4o-mini"
                />
              </label>

              <div className="modal-actions">
                <button type="button" onClick={closeEvalDialog}>
                  Cancel
                </button>
                <button type="submit" disabled={evalLoading}>
                  {evalLoading ? 'Running...' : 'Run Evaluation'}
                </button>
              </div>
            </form>

            {evalLoading ? (
              <div className="modal-progress" aria-live="polite">
                <span className="modal-spinner" aria-hidden="true" />
                <p>Evaluation is in progress...</p>
              </div>
            ) : null}

            {evalResult ? (
              <section className="modal-result-panel" aria-live="polite">
                <h4>Evaluation Result</h4>
                <pre className="dataset-example-code modal-result-code">
                  {JSON.stringify(evalResult, null, 2)}
                </pre>
              </section>
            ) : null}
          </div>
        </div>
      ) : null}

      {samplesDialog.open ? (
        <div className="modal-backdrop" role="presentation" onClick={closeSamplesDialog}>
          <div
            className="modal-card dashboard-card modal-card-wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-samples-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 id="add-samples-title">Add samples</h3>
                <p>Dataset: {samplesDialog.datasetName}</p>
              </div>
              <button type="button" className="modal-close-button" onClick={closeSamplesDialog}>
                Close
              </button>
            </div>

            <div className="modal-tab-strip" role="tablist" aria-label="Sample input modes">
              {[
                ['traces', 'Existing Traces'],
                ['json', 'JSON'],
                ['chat', 'Chat'],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={samplesDialog.mode === mode ? 'modal-tab active' : 'modal-tab'}
                  onClick={() =>
                    setSamplesDialog((current) => ({
                      ...current,
                      mode,
                      resultText: '',
                    }))
                  }
                >
                  {label}
                </button>
              ))}
            </div>

            <form className="modal-form" onSubmit={handleSubmitSamplesDialog}>
              {samplesDialog.mode === 'traces' ? (
                <section className="modal-panel">
                  <div className="modal-panel-header">
                    <div>
                      <h4>Existing traces</h4>
                      <p>Select one or more traces to convert into dataset samples.</p>
                    </div>
                    <label className="traces-select-all">
                      <input
                        type="checkbox"
                        checked={traces.length > 0 && samplesDialog.selectedTraceIds.length === traces.length}
                        onChange={toggleAllTraces}
                      />
                      Select all
                    </label>
                  </div>
                  {tracesLoading ? <p>Loading traces...</p> : null}
                  <div className="modal-trace-list">
                    {traces.map((trace) => (
                      <label key={trace.id} className="modal-trace-row">
                        <input
                          type="checkbox"
                          checked={samplesDialog.selectedTraceIds.includes(trace.id)}
                          onChange={() => toggleTraceSelection(trace.id)}
                        />
                        <span className="modal-trace-main">
                          <strong>{trace.prompt}</strong>
                          <small>{trace.model} · {trace.created_at ? new Date(trace.created_at).toLocaleString() : '-'}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                </section>
              ) : null}

              {samplesDialog.mode === 'json' ? (
                <label>
                  <span>JSON payload</span>
                  <textarea
                    className="modal-textarea"
                    rows={14}
                    value={samplesDialog.jsonText}
                    onChange={(event) =>
                      setSamplesDialog((current) => ({ ...current, jsonText: event.target.value }))
                    }
                  />
                  <small>Paste legacy JSON or a structured payload. The backend will normalize it.</small>
                </label>
              ) : null}

              {samplesDialog.mode === 'chat' ? (
                <section className="modal-panel">
                  <label>
                    <span>Input</span>
                    <input
                      value={samplesDialog.chatInput}
                      onChange={(event) =>
                        setSamplesDialog((current) => ({ ...current, chatInput: event.target.value }))
                      }
                      placeholder="Where is my order?"
                    />
                  </label>
                  <label>
                    <span>Context</span>
                    <textarea
                      className="modal-textarea"
                      rows={6}
                      value={samplesDialog.chatContext}
                      onChange={(event) =>
                        setSamplesDialog((current) => ({ ...current, chatContext: event.target.value }))
                      }
                      placeholder="One context item per line"
                    />
                    <small>Enter one context item per line.</small>
                  </label>
                  <label>
                    <span>Expected output</span>
                    <textarea
                      className="modal-textarea"
                      rows={6}
                      value={samplesDialog.chatExpectedOutput}
                      onChange={(event) =>
                        setSamplesDialog((current) => ({
                          ...current,
                          chatExpectedOutput: event.target.value,
                        }))
                      }
                      placeholder="Your order was shipped yesterday."
                    />
                  </label>
                </section>
              ) : null}

              <div className="modal-actions">
                <button type="button" onClick={closeSamplesDialog}>
                  Cancel
                </button>
                <button type="submit" disabled={samplesDialog.submitLoading}>
                  {samplesDialog.submitLoading ? 'Saving...' : 'Save samples'}
                </button>
              </div>
            </form>

            {samplesDialog.submitLoading ? (
              <div className="modal-progress" aria-live="polite">
                <span className="modal-spinner" aria-hidden="true" />
                <p>Saving samples...</p>
              </div>
            ) : null}

            {samplesDialog.resultText ? (
              <section className="modal-result-panel" aria-live="polite">
                <h4>Result</h4>
                <p>{samplesDialog.resultText}</p>
              </section>
            ) : null}
          </div>
        </div>
      ) : null}

      {samplesViewDialog.open ? (
        <div className="modal-backdrop" role="presentation" onClick={closeViewSamplesDialog}>
          <div
            className="modal-card dashboard-card modal-card-wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="view-samples-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 id="view-samples-title">View samples</h3>
                <p>Dataset: {samplesViewDialog.datasetName}</p>
              </div>
              <button type="button" className="modal-close-button" onClick={closeViewSamplesDialog}>
                Close
              </button>
            </div>

            {samplesViewDialog.loading ? (
              <div className="modal-progress" aria-live="polite">
                <span className="modal-spinner" aria-hidden="true" />
                <p>Loading samples...</p>
              </div>
            ) : null}

            {!samplesViewDialog.loading ? (
              <div className="table-shell modal-inline-table">
                <table className="clean-table modal-sample-table">
                  <thead>
                    <tr>
                      <th>Input</th>
                      <th>Expected output</th>
                      <th>Context</th>
                      <th>Created at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {samplesViewDialog.samples.length > 0 ? (
                      samplesViewDialog.samples.map((sample) => (
                        <tr key={sample.id}>
                          <td className="table-cell-ellipsis">{sample.input}</td>
                          <td className="table-cell-ellipsis">{sample.expected_output}</td>
                          <td className="table-cell-ellipsis">
                            {Array.isArray(sample.context)
                              ? sample.context.join(' | ')
                              : sample.context
                                ? String(sample.context)
                                : '-'}
                          </td>
                          <td>{sample.created_at ? new Date(sample.created_at).toLocaleString() : '-'}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="4">No samples found for this dataset.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
