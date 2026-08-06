/**
 * Overview charts from the LIVE NYC Open Data SODA API (no local cache).
 *
 * What this shows:
 *  - Violations by borough (bar)
 *  - Violations by class A/B/C (bar)
 *  - Top current statuses (bar)
 *  - Monthly inspection trend (line)
 *
 * Where the numbers come from:
 *   Django GET /api/soda-violations/stats/ → live Socrata group-bys
 *
 * Non-technical tip:
 *   On first load, charts can take 1–3 minutes (remote aggregate on ~3M rows).
 *   Click Refresh to pull fresh numbers. You need SOCRATA_APP_TOKEN in .env
 *   and Django running — you do NOT need the AI service for these charts.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { STATIC_LOCAL_ONLY_NOTE, fetchSodaStats, isStaticSnapshot } from './api'

/**
 * One bar chart card. Expects data like [{ name: "BRONX", value: 123 }, ...]
 */
function BarStatChart({ title, data, layout = 'horizontal' }) {
  const points = Array.isArray(data) ? data : []

  if (!points.length) {
    return (
      <div className="analysis-card chart-card">
        <h3>{title}</h3>
        <p className="muted">No data for this chart yet.</p>
      </div>
    )
  }

  const isVertical = layout === 'vertical'

  return (
    <div className="analysis-card chart-card">
      <h3>{title}</h3>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart
            data={points}
            layout={isVertical ? 'vertical' : 'horizontal'}
            margin={{ top: 8, right: 12, left: 8, bottom: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#d5dbe3" />
            {isVertical ? (
              <>
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={120}
                  tick={{ fontSize: 11 }}
                />
              </>
            ) : (
              <>
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
              </>
            )}
            <Tooltip
              formatter={(value) =>
                typeof value === 'number' ? value.toLocaleString() : value
              }
            />
            <Legend />
            <Bar
              dataKey="value"
              name="Violations"
              fill="#0b5fff"
              maxBarSize={48}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/**
 * Monthly trend as a line chart (oldest month on the left).
 */
function MonthTrendChart({ title, data }) {
  const points = Array.isArray(data) ? data : []

  if (!points.length) {
    return (
      <div className="analysis-card chart-card">
        <h3>{title}</h3>
        <p className="muted">No monthly inspection dates to plot.</p>
      </div>
    )
  }

  return (
    <div className="analysis-card chart-card">
      <h3>{title}</h3>
      <div className="chart-box chart-box-wide">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={points} margin={{ top: 8, right: 12, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d5dbe3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} minTickGap={24} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip
              formatter={(value) =>
                typeof value === 'number' ? value.toLocaleString() : value
              }
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="value"
              name="Inspections"
              stroke="#0b5fff"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function StatsDashboard() {
  const staticMode = isStaticSnapshot()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(!staticMode)
  const [error, setError] = useState('')

  /**
   * Pull fresh chart counts from the live SODA API (via Django).
   * Used on page load and when the user clicks Refresh.
   */
  const loadStats = useCallback(() => {
    if (isStaticSnapshot()) {
      setLoading(false)
      setError(STATIC_LOCAL_ONLY_NOTE)
      return Promise.resolve(null)
    }
    setLoading(true)
    setError('')

    return fetchSodaStats()
      .then((data) => {
        setStats(data)
        setLoading(false)
        return data
      })
      .catch((err) => {
        setError(err.message || 'Could not load dashboard stats.')
        setLoading(false)
        throw err
      })
  }, [])

  // Page load — ask the backend for live aggregates (skipped on static snapshot)
  useEffect(() => {
    if (staticMode) return undefined
    let cancelled = false
    setLoading(true)
    setError('')

    fetchSodaStats()
      .then((data) => {
        if (!cancelled) {
          setStats(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Could not load dashboard stats.')
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [staticMode])

  // Public Vercel snapshot: do not call Django; point readers to the journey below
  if (staticMode) {
    return (
      <section className="stats-dashboard" aria-label="Overview charts unavailable on static site">
        <div className="analysis-heading">
          <div>
            <h2>Overview charts</h2>
            <p className="lede-sm">{STATIC_LOCAL_ONLY_NOTE}</p>
            <p className="lede-sm">
              Scroll to <strong>Analysis journey</strong>, or use{' '}
              <strong>Jump to key insight</strong> at the top for the main finding.
            </p>
          </div>
          <span className="pill muted">Local development only</span>
        </div>
      </section>
    )
  }

  const ready = Boolean(stats?.api_ready)
  const rowLabel = (stats?.row_count || 0).toLocaleString()

  return (
    <section className="stats-dashboard" aria-label="Violation overview charts">
      <div className="analysis-heading">
        <div>
          <h2>Overview charts</h2>
          <p className="lede-sm">
            Live counts from NYC Open Data (SODA API). First load can take a
            few minutes; click Refresh anytime for the newest numbers.
          </p>
        </div>
        <div className="stats-actions">
          {ready ? (
            <span className="pill ok">{rowLabel} live rows</span>
          ) : (
            <span className="pill warn">{loading ? 'Loading live data…' : 'API unavailable'}</span>
          )}
          <button
            type="button"
            className="ghost-btn"
            onClick={() => loadStats().catch(() => {})}
            disabled={loading}
            title="Re-query NYC Open Data for fresh chart counts"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {loading && <p className="muted">Loading live chart counts from NYC Open Data…</p>}
      {error && <p className="error-text">{error}</p>}
      {stats?.message && <p className="error-text">{stats.message}</p>}

      {!loading && ready && (
        <div className="stats-grid">
          <BarStatChart title="By borough" data={stats.by_boro} />
          <BarStatChart title="By class" data={stats.by_class} />
          <BarStatChart
            title="Top current statuses"
            data={stats.by_currentstatus}
            layout="vertical"
          />
          <MonthTrendChart
            title="Inspections by month (recent)"
            data={stats.by_month}
          />
        </div>
      )}

      {stats?.notes && !loading && ready && (
        <p className="meta-line">{stats.notes}</p>
      )}
    </section>
  )
}
