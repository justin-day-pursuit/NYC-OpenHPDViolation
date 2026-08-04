/**
 * AI analysis panel that sits UNDER the inventory list.
 *
 * What it does:
 *  1) Shows a prompt bar (press Enter to run).
 *  2) On first use in this browser tab, tells Django to attach the dataset.
 *  3) Scrolls so the prompt bar sits at the top of the window.
 *  4) Renders Gemini's narrative, tables, and charts underneath.
 *
 * Non-technical tip:
 *   If you see "Could not reach the AI analysis service", start the AI app:
 *     cd ai-service && source .venv/bin/activate
 *     uvicorn app.main:app --reload --port 8001
 */

import { useEffect, useRef, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { analyzeWithAi } from './api'
import {
  getAnalysisSessionId,
  hasSentAnalysisData,
  markAnalysisDataSent,
} from './session'

// Soft palette for pie slices (avoid neon / purple glow look)
const PIE_COLORS = ['#0b5fff', '#0f7a43', '#9a6b12', '#9a3412', '#5c6b7a', '#2f6f8f']

/**
 * Draw one chart object returned by the AI.
 * Supported types: bar, line, pie.
 */
function AnalysisChart({ chart, index }) {
  const data = Array.isArray(chart?.data) ? chart.data : []
  const xKey = chart?.xKey || 'name'
  const yKey = chart?.yKey || 'value'
  const title = chart?.title || `Chart ${index + 1}`
  const type = (chart?.type || 'bar').toLowerCase()

  if (!data.length) {
    return (
      <div className="analysis-card">
        <h3>{title}</h3>
        <p className="muted">No chart points returned.</p>
      </div>
    )
  }

  return (
    <div className="analysis-card chart-card">
      <h3>{title}</h3>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height={280}>
          {type === 'line' ? (
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d5dbe3" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey={yKey} stroke="#0b5fff" strokeWidth={2} />
            </LineChart>
          ) : type === 'pie' ? (
            <PieChart>
              <Tooltip />
              <Legend />
              <Pie
                data={data}
                dataKey={yKey}
                nameKey={xKey}
                outerRadius={100}
                label
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d5dbe3" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey={yKey} fill="#0b5fff" />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/**
 * Draw a simple HTML table from AI output.
 */
function AnalysisTable({ table, index }) {
  const columns = table?.columns?.length
    ? table.columns
    : Object.keys((table?.rows && table.rows[0]) || {})
  const rows = Array.isArray(table?.rows) ? table.rows : []

  return (
    <div className="analysis-card">
      <h3>{table?.title || `Table ${index + 1}`}</h3>
      {!rows.length ? (
        <p className="muted">No rows.</p>
      ) : (
        <div className="mini-table-wrap">
          <table className="mini-table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {columns.map((col) => (
                    <td key={col}>{row?.[col] ?? '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function AnalysisPanel() {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [dataSent, setDataSent] = useState(hasSentAnalysisData())

  // This ref lets us scroll the prompt bar to the top of the page
  const panelRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    setDataSent(hasSentAnalysisData())
  }, [])

  /**
   * Run when the user presses Enter in the prompt bar.
   */
  async function handleSubmit(event) {
    event.preventDefault()
    const text = prompt.trim()
    if (!text || loading) return

    setError('')
    setLoading(true)

    // Scroll so the prompt bar sits at the top of the viewport,
    // then results load underneath as you read downward.
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

    const sessionId = getAnalysisSessionId()
    const includeData = !hasSentAnalysisData()

    try {
      const data = await analyzeWithAi({
        prompt: text,
        sessionId,
        includeData,
      })
      setResult(data)
      if (data.session_data_was_sent || data.data_included || includeData) {
        markAnalysisDataSent()
        setDataSent(true)
      }
    } catch (err) {
      setError(err.message || 'Analysis failed.')
    } finally {
      setLoading(false)
      // Keep focus ready for the next question
      inputRef.current?.focus()
    }
  }

  return (
    <section className="analysis-panel" ref={panelRef} aria-label="AI data analysis">
      <div className="analysis-heading">
        <div>
          <h2>Ask AI to analyze the data</h2>
          <p className="lede-sm">
            Press Enter to send your prompt. The full local dataset summary is attached
            once per browser tab; follow-ups only send the new question.
          </p>
        </div>
        <span className={`pill ${dataSent ? 'ok' : 'muted'}`}>
          {dataSent ? 'Dataset already attached this session' : 'Next request will attach dataset'}
        </span>
      </div>

      {/* Prompt bar — Enter submits */}
      <form className="prompt-bar" onSubmit={handleSubmit}>
        <label className="prompt-label" htmlFor="ai-prompt">
          Analysis prompt
        </label>
        <input
          id="ai-prompt"
          ref={inputRef}
          type="search"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='Example: "Show Class C violations by borough as a bar chart"'
          disabled={loading}
          autoComplete="off"
        />
        <button type="submit" disabled={loading || !prompt.trim()}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </form>

      {error && <p className="error-text">{error}</p>}

      {/* Results render under the prompt bar */}
      {result && (
        <div className="analysis-results">
          {result.narrative && (
            <div className="analysis-card">
              <h3>Findings</h3>
              <p className="narrative">{result.narrative}</p>
              <p className="meta-line">
                Model {result.model}
                {result.row_count_context != null
                  ? ` · context rows ${Number(result.row_count_context).toLocaleString()}`
                  : ''}
                {result.session_data_was_sent ? ' · data pack sent this turn' : ' · reused session data'}
              </p>
            </div>
          )}

          {(result.charts || []).map((chart, index) => (
            <AnalysisChart key={`chart-${index}`} chart={chart} index={index} />
          ))}

          {(result.tables || []).map((table, index) => (
            <AnalysisTable key={`table-${index}`} table={table} index={index} />
          ))}

          {!!(result.manipulated_rows || []).length && (
            <div className="analysis-card">
              <h3>Manipulated / example rows</h3>
              <div className="mini-table-wrap">
                <table className="mini-table">
                  <thead>
                    <tr>
                      {Object.keys(result.manipulated_rows[0] || {}).map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.manipulated_rows.map((row, i) => (
                      <tr key={i}>
                        {Object.keys(result.manipulated_rows[0] || {}).map((col) => (
                          <td key={col}>{row?.[col] ?? '—'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
