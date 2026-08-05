/**
 * Analysis journey section — building concentration of open HPD violations.
 *
 * Where this sits on the page:
 *   Directly under "Overview charts", before the inventory toolbar.
 *
 * Where the numbers come from:
 *   A snapshot JSON file produced by notebooks/run_building_concentration.py
 *   (live SODA aggregates, deduped by violationid). Path:
 *     /analysis/building_concentration.json
 *
 * How a non-technical maintainer refreshes the numbers:
 *   1) From notebooks/:  source .venv/bin/activate
 *   2) Run:              python run_building_concentration.py
 *   3) Then:             python run_hazard_theme_analysis.py
 *   4) Then:             python run_final_insight.py
 *   5) Reload this webpage.
 *
 * Charts follow the same visual rules as Overview:
 *   bar axes start at 0, shared colors, even card spacing.
 */

import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

/** Shared chart colors — keep in sync with Overview / App.css accent */
const ACCENT = '#0b5fff'
const SECONDARY = '#5c6b7a'
const MUTED_BAR = '#b0bac4'
const GRID = '#d5dbe3'
const CHART_HEIGHT = 280
const CHART_MARGIN = { top: 8, right: 12, left: 8, bottom: 8 }

/** Format a UTC ISO timestamp for the caption under the section. */
function formatGeneratedAt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

/**
 * One chart card with a title. Always reserves the same height so cards
 * line up evenly in the grid.
 */
function ChartCard({ title, children }) {
  return (
    <div className="analysis-card chart-card">
      <h3>{title}</h3>
      <div className="chart-box">{children}</div>
    </div>
  )
}

/** Percent tooltip helper for Recharts */
function pctTooltip(value) {
  return typeof value === 'number' ? `${value.toLocaleString()}%` : value
}

/**
 * Step 2 chart: share of open violations held by the top X% of buildings.
 * Y-axis forced to start at 0 and end at 100 for fair comparison.
 */
function TopShareChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Share of open violations in the most-burdened buildings">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Share of open violations (%)',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={pctTooltip}
            labelFormatter={(label, payload) => {
              const buildings = payload?.[0]?.payload?.buildings
              return buildings
                ? `${label} (${buildings.toLocaleString()} buildings)`
                : label
            }}
          />
          <Bar
            dataKey="violation_share_pct"
            name="% of open violations"
            fill={ACCENT}
            maxBarSize={48}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Lorenz / concentration curve vs a perfect-equality diagonal.
 * X = cumulative % of buildings (most burdened first in the source math,
 * plotted as percentile of buildings ranked by burden).
 */
function LorenzChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  // Add equality line (y = x) so readers can see the gap at a glance
  const withEquality = points.map((p) => ({
    ...p,
    equality: p.building_percentile,
  }))

  return (
    <ChartCard title="Concentration curve (buildings → open violations)">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={withEquality} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis
            dataKey="building_percentile"
            type="number"
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Buildings ranked by open violations (cumulative %)',
              position: 'insideBottom',
              offset: -2,
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Cumulative % of open violations',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={(value, name) => [
              typeof value === 'number' ? `${value.toFixed(1)}%` : value,
              name,
            ]}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="equality"
            name="Equal distribution"
            stroke={SECONDARY}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="violation_percentile"
            name="Actual open violations"
            stroke={ACCENT}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Bucket chart: % of buildings vs % of violations by open-count bucket.
 * Grouped bars, both series on a 0–100% axis.
 */
function BucketChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Open violations per building — who holds the inventory?">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 12 }}
            label={{
              value: 'Open violations per building',
              position: 'insideBottom',
              offset: -2,
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip formatter={pctTooltip} />
          <Legend />
          <Bar
            dataKey="building_share_pct"
            name="% of buildings"
            fill={SECONDARY}
            maxBarSize={40}
          />
          <Bar
            dataKey="violation_share_pct"
            name="% of open violations"
            fill={ACCENT}
            maxBarSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/** Class mix: citywide vs top 1% of buildings (share of open violations). */
function ClassCompareChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Violation class mix — citywide vs top 1% of buildings">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Share of open violations (%)',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip formatter={pctTooltip} />
          <Legend />
          <Bar dataKey="citywide" name="Citywide" fill={SECONDARY} maxBarSize={40} />
          <Bar
            dataKey="top_1pct_buildings"
            name="Top 1% buildings"
            fill={ACCENT}
            maxBarSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Status mix: citywide vs top 200 buildings — highlights the no-access lift.
 */
function StatusCompareChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Open status mix — citywide vs top 200 buildings">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart
          data={points}
          layout="vertical"
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={150}
            tick={{ fontSize: 11 }}
          />
          <Tooltip formatter={pctTooltip} />
          <Legend />
          <Bar dataKey="citywide" name="Citywide" fill={SECONDARY} maxBarSize={28} />
          <Bar
            dataKey="top_200_buildings"
            name="Top 200 buildings"
            fill={ACCENT}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/** Borough chart: top-10% building share of open violations (similarity check). */
function BoroChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Top 10% of buildings — open-violation share by borough">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip formatter={pctTooltip} />
          <Bar
            dataKey="top_10pct_share_pct"
            name="Share held by top 10% of buildings"
            fill={ACCENT}
            maxBarSize={48}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Structure proxy chart for top buildings (apartment / story signals).
 * Y-axis is building count; always starts at 0.
 */
function StructureTypeChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null
  // Force baseline at 0 (bar-chart rule); pad the top a little for labels
  const yMax = Math.max(...points.map((p) => Number(p.buildings) || 0), 1)

  return (
    <ChartCard title="Top 200 buildings — structure signal from open violations">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, Math.ceil(yMax * 1.1)]}
            allowDecimals={false}
            tick={{ fontSize: 12 }}
            label={{
              value: 'Buildings',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={(value, name, item) => {
              const share = item?.payload?.share_pct
              if (typeof value === 'number' && typeof share === 'number') {
                return [`${value.toLocaleString()} (${share}%)`, 'Buildings']
              }
              return [value, name]
            }}
          />
          <Bar dataKey="buildings" name="Buildings" fill={ACCENT} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/** How widely open violations touch distinct apartments in the top 200. */
function ApartmentSpreadChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null
  const yMax = Math.max(...points.map((p) => Number(p.buildings) || 0), 1)

  return (
    <ChartCard title="Top 200 — distinct apartments with open violations">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, Math.ceil(yMax * 1.1)]}
            allowDecimals={false}
            tick={{ fontSize: 12 }}
            label={{
              value: 'Buildings',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={(value, name, item) => {
              const share = item?.payload?.share_pct
              if (typeof value === 'number' && typeof share === 'number') {
                return [`${value.toLocaleString()} (${share}%)`, 'Buildings']
              }
              return [value, name]
            }}
          />
          <Bar dataKey="buildings" name="Buildings" fill={ACCENT} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/** Short label for structure_proxy codes shown in the table */
function structureLabel(code) {
  if (code === 'multi_dwelling_complex') return 'Multi-dwelling'
  if (code === 'multi_unit_or_multi_story') return 'Multi-unit / multi-story'
  if (code === 'limited_unit_signal') return 'Limited signal'
  return code || '—'
}

/**
 * Share of open violations inspected before 2020, by class.
 * Compares citywide vs top 200 buildings (Y starts at 0).
 */
function Pre2020ByClassChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Share of open violations inspected before 2020">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Share of open violations (%)',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip formatter={pctTooltip} />
          <Legend />
          <Bar dataKey="citywide" name="Citywide" fill={SECONDARY} maxBarSize={40} />
          <Bar
            dataKey="top_200_buildings"
            name="Top 200 buildings"
            fill={ACCENT}
            maxBarSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Median inspection year by class — shown as a compact table (not a bar from 0,
 * which would misrepresent calendar years).
 */
function MedianYearTable({ data }) {
  const rows = Array.isArray(data) ? data : []
  if (!rows.length) return null

  return (
    <div className="analysis-card chart-card">
      <h3>Median inspection year of currently open violations</h3>
      <div className="journey-table-wrap">
        <table className="journey-table">
          <thead>
            <tr>
              <th scope="col">Class</th>
              <th scope="col">Citywide median year</th>
              <th scope="col">Top 200 median year</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td className="num">{row.citywide_median_year ?? '—'}</td>
                <td className="num">{row.top200_median_year ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="meta-line" style={{ marginTop: '0.65rem' }}>
        Lower median year = older open inventory. Class B citywide (2019) is the
        clear aging backlog versus Class C (2023).
      </p>
    </div>
  )
}

/**
 * Problem-theme rates: citywide vs top 200 (keyword match on novdescription).
 * Sorted by lift in the snapshot JSON.
 */
function ThemeCompareChart({ data }) {
  const points = Array.isArray(data) ? data.slice(0, 8) : []
  if (!points.length) return null
  const yMax = Math.max(
    ...points.flatMap((p) => [Number(p.citywide) || 0, Number(p.top_200_buildings) || 0]),
    1,
  )

  return (
    <ChartCard title="Problem themes in open NOV text — citywide vs top 200">
      <ResponsiveContainer width="100%" height={320}>
        <BarChart
          data={points}
          layout="vertical"
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis
            type="number"
            domain={[0, Math.ceil(yMax * 1.15)]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
          />
          <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value, name, item) => {
              const lift = item?.payload?.lift
              const base =
                typeof value === 'number' ? `${value.toLocaleString()}%` : value
              if (name === 'Top 200 buildings' && lift != null) {
                return [`${base} (${lift}× city)`, name]
              }
              return [base, name]
            }}
          />
          <Legend />
          <Bar dataKey="citywide" name="Citywide" fill={SECONDARY} maxBarSize={22} />
          <Bar
            dataKey="top_200_buildings"
            name="Top 200 buildings"
            fill={ACCENT}
            maxBarSize={22}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/** Primary theme mix among Class C opens in the top 200 buildings. */
function ClassCThemeChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null
  const yMax = Math.max(...points.map((p) => Number(p.share_pct) || 0), 1)

  return (
    <ChartCard title="Top 200 buildings — primary theme of Class C opens">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart
          data={points}
          layout="vertical"
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis
            type="number"
            domain={[0, Math.ceil(yMax * 1.15)]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
          />
          <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
          <Tooltip formatter={pctTooltip} />
          <Bar dataKey="share_pct" name="Share of Class C opens" fill={ACCENT} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

/**
 * Final insight — age×theme: pre-2020 share by slice.
 * Highlighted bar = Class B mold/water (moisture channel inside Class B backlog).
 */
function FinalAgeCompareChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null

  return (
    <ChartCard title="Age×theme — share of opens inspected before 2020">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Share inspected before 2020 (%)',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={(value, _name, item) => {
              const role = item?.payload?.role
              const median = item?.payload?.median_year
              const base = typeof value === 'number' ? `${value}%` : value
              const extra = [role, median != null ? `median year ${median}` : null]
                .filter(Boolean)
                .join(' · ')
              return [extra ? `${base} — ${extra}` : base, 'Pre-2020 share']
            }}
          />
          <Bar dataKey="share_pre_2020_pct" name="Pre-2020 share" maxBarSize={48}>
            {points.map((entry) => (
              <Cell
                key={entry.name}
                fill={entry.highlight ? ACCENT : MUTED_BAR}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="meta-line" style={{ marginTop: '0.5rem' }}>
        Highlighted: Class B mold/water — older than Class C, inside the Class B
        backlog (Class B other is even older).
      </p>
    </ChartCard>
  )
}

/**
 * Final insight — Class B∧mold|water share of opens by burden tier.
 * Highlighted bar = top 200.
 */
function FinalTierGradientChart({ data }) {
  const points = Array.isArray(data)
    ? data.map((p) => ({ ...p, label: p.short || p.name }))
    : []
  if (!points.length) return null
  const yMax = Math.max(...points.map((p) => Number(p.class_B_mold_water_pct) || 0), 1)

  return (
    <ChartCard title="Class B mold/water share of opens — rises with burden">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, Math.ceil(yMax * 1.25)]}
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: 'Share of open violations (%)',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip
            formatter={(value, _name, item) => {
              const mold = item?.payload?.mold_water_pct
              const base = typeof value === 'number' ? `${value}%` : value
              return [
                mold != null ? `${base} (all mold/water ${mold}%)` : base,
                'Class B ∧ mold/water',
              ]
            }}
          />
          <Bar dataKey="class_B_mold_water_pct" name="Class B ∧ mold/water" maxBarSize={48}>
            {points.map((entry) => (
              <Cell
                key={entry.label}
                fill={entry.highlight ? ACCENT : MUTED_BAR}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="meta-line" style={{ marginTop: '0.5rem' }}>
        Highlighted: top 200 high-burden buildings — Class B moisture intensifies
        versus citywide.
      </p>
    </ChartCard>
  )
}

/**
 * Final insight — multi-dwelling vs limited-unit building counts.
 * Shows single-ish stock is absent from the top open-violation tier.
 */
function FinalStructureCountsChart({ data }) {
  const points = Array.isArray(data) ? data : []
  if (!points.length) return null
  const yMax = Math.max(
    ...points.flatMap((p) => [Number(p.top_200) || 0, Number(p.lower_burden) || 0]),
    1,
  )

  return (
    <ChartCard title="Building structure proxy — top 200 vs lower-burden band">
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={points} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
          <YAxis
            domain={[0, Math.ceil(yMax * 1.15)]}
            allowDecimals={false}
            tick={{ fontSize: 12 }}
            label={{
              value: 'Buildings',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SECONDARY },
            }}
          />
          <Tooltip />
          <Legend />
          <Bar dataKey="top_200" name="Top 200 (high burden)" fill={ACCENT} maxBarSize={40} />
          <Bar
            dataKey="lower_burden"
            name="Lower-burden band"
            fill={MUTED_BAR}
            maxBarSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
      <p className="meta-line" style={{ marginTop: '0.5rem' }}>
        Limited-unit / single-ish buildings: 0 in the top 200, present only in
        lower-burden stock. Extreme opens are a multi-dwelling phenomenon.
      </p>
    </ChartCard>
  )
}

export default function ConcentrationJourney() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // Load the snapshot JSON once on mount (no Django required for this section)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')

    fetch('/analysis/building_concentration.json')
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Could not load analysis snapshot (${res.status})`)
        }
        return res.json()
      })
      .then((json) => {
        if (!cancelled) {
          setData(json)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Could not load analysis journey.')
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const headlines = data?.headlines
  const charts = data?.charts
  const insight = data?.insight
  const meta = data?.meta
  const held = data?.hypothesis?.result === 'not_disproved'

  return (
    <section
      className="concentration-journey"
      aria-label="Building concentration analysis journey"
    >
      <div className="analysis-heading">
        <div>
          <h2>Analysis journey</h2>
          <p className="lede-sm">
            Testing whether open HPD violations concentrate in a small fraction
            of buildings — and what that implies for enforcement. Counts use
            distinct <code>violationid</code> only (duplicates / escalations
            entered twice count once). Open violations only.
          </p>
        </div>
        {headlines && (
          <div className="stats-actions">
            <span className={`pill ${held ? 'ok' : 'warn'}`}>
              {held ? 'Hypothesis not disproved' : 'Hypothesis weakened'}
            </span>
            <span className="pill muted">
              Gini {headlines.gini}
            </span>
          </div>
        )}
      </div>

      {loading && (
        <p className="muted">Loading building concentration analysis…</p>
      )}
      {error && (
        <p className="error-text">
          {error}{' '}
          <span className="muted">
            Tip: run <code>python run_building_concentration.py</code> from{' '}
            <code>notebooks/</code>.
          </span>
        </p>
      )}

      {!loading && data && (
        <>
          {/* Headline KPIs — one row, even spacing */}
          <div className="journey-kpis" aria-label="Key concentration findings">
            <div className="journey-kpi">
              <span className="journey-kpi-value">
                {headlines.top_10pct_violation_share_pct}%
              </span>
              <span className="journey-kpi-label">
                of open violations sit in the top 10% of buildings
              </span>
            </div>
            <div className="journey-kpi">
              <span className="journey-kpi-value">
                {headlines.buildings_pct_for_half_violations}%
              </span>
              <span className="journey-kpi-label">
                of buildings hold half of all open violations
                ({headlines.buildings_for_half_violations.toLocaleString()}{' '}
                buildings)
              </span>
            </div>
            <div className="journey-kpi">
              <span className="journey-kpi-value">
                {headlines.tail_101plus_violation_pct}%
              </span>
              <span className="journey-kpi-label">
                of open violations are in buildings with 101+ opens
                ({headlines.tail_101plus_building_pct}% of buildings)
              </span>
            </div>
            <div className="journey-kpi">
              <span className="journey-kpi-value">
                {headlines.no_access_lift}×
              </span>
              <span className="journey-kpi-label">
                higher “no access to re-inspect” share in the top 200 buildings
              </span>
            </div>
          </div>

          {/* Step 1 — question & method */}
          <div className="journey-step">
            <h3 className="journey-step-title">Step 1 — Question &amp; method</h3>
            <ul className="journey-points">
              <li>
                <strong>Hypothesis:</strong> {data.hypothesis.statement}
              </li>
              <li>
                <strong>Unit:</strong> each <code>buildingid</code> with at least
                one currently open violation (
                {meta.buildings_with_open_violations.toLocaleString()} buildings;{' '}
                {meta.total_open_violations_deduped.toLocaleString()} distinct open
                violations).
              </li>
              <li>
                <strong>Deduping:</strong> {meta.dedupe_rule} In this snapshot,{' '}
                {meta.duplicate_violationid_rows_removed.toLocaleString()} duplicate
                rows were removed.
              </li>
              <li>
                <strong>Decision rule:</strong> {data.hypothesis.decision_rule}
              </li>
            </ul>
          </div>

          {/* Step 2 — concentration test */}
          <div className="journey-step">
            <h3 className="journey-step-title">
              Step 2 — Concentration test{' '}
              <span className={`pill ${held ? 'ok' : 'warn'}`}>
                {held ? 'Not disproved' : 'Disproved / weak'}
              </span>
            </h3>
            <ul className="journey-points">
              <li>
                The top 10% of buildings account for{' '}
                <strong>{headlines.top_10pct_violation_share_pct}%</strong> of
                open violations — above the “well over half” bar we set.
              </li>
              <li>
                Half of all open violations sit in just{' '}
                <strong>{headlines.buildings_pct_for_half_violations}%</strong> of
                buildings with any open violation.
              </li>
              <li>
                The long tail is real: buildings with 101+ open violations are
                only {headlines.tail_101plus_building_pct}% of buildings but hold{' '}
                {headlines.tail_101plus_violation_pct}% of the open inventory.
              </li>
            </ul>
            <div className="stats-grid journey-grid">
              <TopShareChart data={charts.top_share_bars} />
              <LorenzChart data={data.lorenz_curve} />
              <BucketChart data={charts.bucket_bars} />
            </div>
          </div>

          {/* Step 3 — non-obvious dig */}
          <div className="journey-step">
            <h3 className="journey-step-title">Step 3 — Dig: {insight.title}</h3>
            <p className="journey-claim">{insight.claim}</p>
            <ul className="journey-points">
              <li>
                <strong>Why this is not obvious:</strong> {insight.why_non_obvious}
              </li>
              <li>
                Class C (immediately hazardous) rises from{' '}
                {((insight.metrics.citywide_class_c_share || 0) * 100).toFixed(1)}%
                citywide to{' '}
                {((insight.metrics.top_1pct_class_c_share || 0) * 100).toFixed(1)}%
                in the top 1% of buildings, while Class I (informational) falls
                from{' '}
                {((insight.metrics.citywide_class_i_share || 0) * 100).toFixed(1)}%
                to{' '}
                {((insight.metrics.top_1pct_class_i_share || 0) * 100).toFixed(1)}%.
              </li>
              <li>
                <strong>Actionable angle:</strong> targeting the small set of
                high-burden buildings should pair violation count with access /
                re-inspection status — volume alone understates where the open
                inventory is stuck.
              </li>
            </ul>
            <div className="stats-grid journey-grid">
              <BoroChart data={charts.boro_concentration} />
              <ClassCompareChart data={charts.class_compare} />
              <StatusCompareChart data={charts.status_compare} />
            </div>
          </div>

          {/* Step 4 — are top buildings multi-dwelling / multi-story? */}
          {data.top_building_structure?.finding && (
            <div className="journey-step">
              <h3 className="journey-step-title">
                Step 4 — Dig: {data.top_building_structure.finding.title}
              </h3>
              <p className="journey-claim">
                {data.top_building_structure.finding.summary}
              </p>
              <ul className="journey-points">
                <li>
                  <strong>Method caveat:</strong>{' '}
                  {data.top_building_structure.finding.method_note}
                </li>
                <li>
                  <strong>What we checked:</strong> for the top 200 buildings by
                  open-violation count, how many distinct <code>apartment</code>{' '}
                  labels and <code>story</code> values appear on those open
                  violations — a proxy for multi-dwelling / multi-story stock.
                </li>
                <li>
                  <strong>Result:</strong>{' '}
                  {headlines.top200_multi_dwelling_pct != null
                    ? `${headlines.top200_multi_dwelling_pct}%`
                    : 'Most'}{' '}
                  show a multi-dwelling complex signal;{' '}
                  <strong>{headlines.top200_limited_unit_count ?? 0}</strong> show
                  a limited apartment/story signal. The smallest apartment spread
                  in this top-200 set is{' '}
                  <strong>{headlines.top200_min_apartments}</strong> distinct
                  apartments with opens — we did <em>not</em> find top-burden
                  buildings that look like single-dwelling stock in this open
                  dataset.
                </li>
                <li>
                  Floors reinforce the same picture:{' '}
                  {data.top_building_structure.finding.max_story_at_least_3_buildings}{' '}
                  of 200 have open violations on floor 3+, and{' '}
                  {data.top_building_structure.finding.max_story_at_least_6_buildings}{' '}
                  on floor 6+.
                </li>
              </ul>
              <div className="stats-grid journey-grid">
                <StructureTypeChart data={charts.structure_type_bars} />
                <ApartmentSpreadChart data={charts.apartment_spread_bars} />
              </div>
            </div>
          )}

          {/* Step 5 — hazard persistence (age by class) */}
          {data.hazard_persistence?.finding && (
            <div className="journey-step">
              <h3 className="journey-step-title">
                Step 5 — Dig: {data.hazard_persistence.finding.title}
              </h3>
              <p className="journey-claim">{data.hazard_persistence.finding.claim}</p>
              <ul className="journey-points">
                <li>
                  <strong>Why this is not obvious:</strong>{' '}
                  {data.hazard_persistence.finding.why_non_obvious}
                </li>
                <li>
                  <strong>Citywide:</strong> {headlines.class_b_pre_2020_city_pct}% of open
                  Class B vs {headlines.class_c_pre_2020_city_pct}% of open Class C were
                  inspected before 2020 (median years{' '}
                  {data.hazard_persistence.citywide.median_inspection_year.B} vs{' '}
                  {data.hazard_persistence.citywide.median_inspection_year.C}).
                </li>
                <li>
                  <strong>Top 200 buildings:</strong> open inventory is newer overall, but
                  Class B still lags Class C ({headlines.class_b_pre_2020_top200_pct}% vs{' '}
                  {headlines.class_c_pre_2020_top200_pct}% pre-2020).
                </li>
                <li>
                  <strong>Method:</strong> {data.hazard_persistence.finding.method_note}
                </li>
              </ul>
              <div className="stats-grid journey-grid">
                <Pre2020ByClassChart data={charts.pre_2020_by_class} />
                <MedianYearTable data={charts.median_inspection_year_by_class} />
              </div>
            </div>
          )}

          {/* Step 6 — problem-type clustering from NOV text */}
          {data.problem_type_clustering?.finding && (
            <div className="journey-step">
              <h3 className="journey-step-title">
                Step 6 — Dig: {data.problem_type_clustering.finding.title}
              </h3>
              <p className="journey-claim">
                {data.problem_type_clustering.finding.claim}
              </p>
              <ul className="journey-points">
                <li>
                  <strong>Why this is not obvious:</strong>{' '}
                  {data.problem_type_clustering.finding.why_non_obvious}
                </li>
                <li>
                  <strong>Largest citywide→top-200 lifts:</strong>{' '}
                  {headlines.top_theme_lift_name} ({headlines.top_theme_lift}×).
                </li>
                <li>
                  <strong>Class C inside top 200:</strong>{' '}
                  {headlines.top200_class_c_top_theme} accounts for{' '}
                  {headlines.top200_class_c_top_theme_pct}% of those immediately hazardous
                  opens (primary theme).
                </li>
                <li>
                  <strong>Method:</strong> {data.problem_type_clustering.finding.method_note}
                </li>
              </ul>
              <div className="stats-grid journey-grid">
                <ThemeCompareChart data={charts.theme_lift_bars} />
                <ClassCThemeChart data={charts.top200_class_c_primary_themes} />
              </div>
            </div>
          )}

          {/* Final insight — locks Class B moisture + multi-dwelling + age×theme */}
          {data.final_insight?.finding && (
            <div className="journey-step journey-final">
              <h3 className="journey-step-title">
                Final insight — {data.final_insight.finding.title}
              </h3>

              <p className="journey-claim journey-claim-final">
                {data.final_insight.finding.statement}
              </p>

              <div className="journey-kpis" aria-label="Final insight lock points">
                <div className="journey-kpi journey-kpi-accent">
                  <span className="journey-kpi-value">
                    {headlines.final_top200_multi_buildings}/
                    {data.final_insight.tiers.top_200.buildings}
                  </span>
                  <span className="journey-kpi-label">
                    multi-dwelling in the top 200 ·{' '}
                    {headlines.final_top200_limited_buildings} limited-unit /
                    single-ish
                  </span>
                </div>
                <div className="journey-kpi journey-kpi-accent">
                  <span className="journey-kpi-value">
                    {headlines.final_city_bmw_pct}%→
                    {headlines.final_top200_bmw_pct}%
                  </span>
                  <span className="journey-kpi-label">
                    Class B mold/water share of opens (citywide → top 200)
                  </span>
                </div>
                <div className="journey-kpi journey-kpi-accent">
                  <span className="journey-kpi-value">
                    {headlines.final_bmw_pre_2020_pct}%
                  </span>
                  <span className="journey-kpi-label">
                    of Class B mold/water opens inspected before 2020 (vs{' '}
                    {headlines.final_c_pre_2020_pct}% of Class C)
                  </span>
                </div>
                <div className="journey-kpi">
                  <span className="journey-kpi-value">
                    {headlines.final_b_other_pre_2020_pct}%
                  </span>
                  <span className="journey-kpi-label">
                    of other Class B opens pre-2020 — persistence is Class B
                    broadly; moisture is the high-burden enrichment
                  </span>
                </div>
              </div>

              <ul className="journey-points">
                <li>
                  <strong>Specific:</strong> {data.final_insight.finding.specificity}
                </li>
                <li>
                  <strong>Non-obvious:</strong> {data.final_insight.finding.non_obvious}
                </li>
                <li>
                  <strong>Method:</strong> {data.final_insight.finding.method_note}
                </li>
              </ul>

              <div className="stats-grid journey-grid">
                <FinalTierGradientChart data={charts.final_tier_gradient} />
                <FinalStructureCountsChart data={charts.final_structure_counts} />
                <FinalAgeCompareChart data={charts.final_age_compare} />
              </div>

              <div className="journey-argue-grid">
                <div className="journey-argue">
                  <h4>Arguments that support this</h4>
                  <ul>
                    {(data.final_insight.finding.arguments_for || []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className="journey-argue">
                  <h4>Arguments that cut against it</h4>
                  <ul>
                    {(data.final_insight.finding.arguments_against || []).map(
                      (item) => (
                        <li key={item}>{item}</li>
                      ),
                    )}
                  </ul>
                </div>
              </div>

              <p className="journey-one-liner" role="note">
                <strong>One-sentence insight:</strong>{' '}
                {data.final_insight.finding.one_sentence ||
                  `Prioritize Class B mold/water remediation in high-burden multi-dwelling buildings, where those opens are ${headlines.final_top200_bmw_pct}% of the inventory versus ${headlines.final_city_bmw_pct}% citywide — while limited-unit / single-ish buildings are absent from the top-200 open-violation tier (0 of ${data.final_insight.tiers.top_200.buildings}).`}
              </p>
            </div>
          )}

          {/* Top buildings table for concreteness */}
          {Array.isArray(data.top_buildings) && data.top_buildings.length > 0 && (
            <div className="journey-step">
              <h3 className="journey-step-title">
                Highest open-violation buildings (snapshot)
              </h3>
              <p className="lede-sm">
                Apartment / story columns count distinct labels among each
                building’s <em>currently open</em> violations (not the building’s
                full unit count).
              </p>
              <div className="journey-table-wrap">
                <table className="journey-table">
                  <thead>
                    <tr>
                      <th scope="col">Building ID</th>
                      <th scope="col">Address</th>
                      <th scope="col">Borough</th>
                      <th scope="col">Open violations</th>
                      <th scope="col">Apts w/ opens</th>
                      <th scope="col">Stories w/ opens</th>
                      <th scope="col">Max story</th>
                      <th scope="col">Structure signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_buildings.map((row) => (
                      <tr key={row.buildingid}>
                        <td>{row.buildingid}</td>
                        <td>
                          {[row.housenumber, row.streetname].filter(Boolean).join(' ')}
                          {row.zip ? ` (${row.zip})` : ''}
                        </td>
                        <td>{row.boro}</td>
                        <td className="num">
                          {Number(row.open_violations).toLocaleString()}
                        </td>
                        <td className="num">
                          {row.distinct_apartments_with_opens != null
                            ? Number(row.distinct_apartments_with_opens).toLocaleString()
                            : '—'}
                        </td>
                        <td className="num">
                          {row.distinct_stories_with_opens != null
                            ? Number(row.distinct_stories_with_opens).toLocaleString()
                            : '—'}
                        </td>
                        <td className="num">
                          {row.max_story_observed != null ? row.max_story_observed : '—'}
                        </td>
                        <td>{structureLabel(row.structure_proxy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <p className="meta-line">
            Source: NYC Open Data Open HPD Violations ({meta.dataset_id}) ·{' '}
            {meta.scope} · Deduped by violationid · Snapshot{' '}
            {formatGeneratedAt(meta.generated_at)}
            {meta.hazard_theme_analyzed_at
              ? ` · Hazard/theme pass ${formatGeneratedAt(meta.hazard_theme_analyzed_at)}`
              : ''}
            {meta.final_insight_analyzed_at
              ? ` · Final insight ${formatGeneratedAt(meta.final_insight_analyzed_at)}`
              : ''}
            . Refresh with{' '}
            <code>notebooks/run_building_concentration.py</code>,{' '}
            <code>run_hazard_theme_analysis.py</code>, then{' '}
            <code>run_final_insight.py</code>.
          </p>
        </>
      )}
    </section>
  )
}
