/**
 * Overview charts built from SQL counts (no AI).
 *
 * What this shows:
 *  - Violations by borough (bar)
 *  - Violations by class A/B/C (bar)
 *  - Top current statuses (bar)
 *  - Monthly inspection trend (line)
 *
 * Where the numbers come from:
 *   Django endpoint GET /api/soda-violations/stats/
 *   which reads the local SQLite cache (backend/data/soda_violations.sqlite3).
 *
 * Non-technical tip:
 *   If charts say the cache is empty, open a terminal and run:
 *     cd backend
 *     source .venv/bin/activate
 *     python manage.py fetch_soda_violations
 *   Then refresh this page. You do not need the AI service for these charts.
 */

import { useEffect, useState } from 'react'
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
import { fetchSodaStats } from './api'

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

  // Vertical bars for short category lists; horizontal for long status labels
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
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Load once when the page opens (full-cache overview — not tied to list filters)
  useEffect(() => {
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
  }, [])

  return (
    <section className="stats-dashboard" aria-label="Violation overview charts">
      <div className="analysis-heading">
        <div>
          <h2>Overview charts</h2>
          <p className="lede-sm">
            Counts from the full local table (SQL). These update when you
            re-download the SODA cache — they do not need the AI service.
          </p>
        </div>
        {stats?.cache_ready ? (
          <span className="pill ok">
            {(stats.row_count || 0).toLocaleString()} rows in charts
          </span>
        ) : (
          <span className="pill warn">Cache empty</span>
        )}
      </div>

      {loading && <p className="muted">Loading chart counts…</p>}
      {error && <p className="error-text">{error}</p>}
      {stats?.message && <p className="error-text">{stats.message}</p>}

      {/* Only draw charts once we have a ready cache */}
      {!loading && stats?.cache_ready && (
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

      {stats?.notes && !loading && stats?.cache_ready && (
        <p className="meta-line">{stats.notes}</p>
      )}
    </section>
  )
}
