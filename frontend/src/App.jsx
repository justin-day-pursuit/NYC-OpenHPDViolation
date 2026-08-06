/**
 * Inventory-style Open HPD Violations browser + overview charts + AI panel.
 *
 * Shows EVERY column returned by the SODA cache (even when blank).
 * Layout:
 *  - overview charts from SQL (borough / class / status / monthly)
 *  - analysis journey (building concentration of open violations)
 *  - key insight at the bottom of that journey (#data-insight)
 *  - toolbar with search, filters, sort, and page size
 *  - horizontally scrollable item list with sortable column headers
 *  - AI prompt bar under the list (Enter = analyze with Gemini)
 *  - analysis narrative / tables / charts render under the prompt
 *
 * Tip: set SOCRATA_APP_TOKEN in the root .env so live SODA requests work.
 * Charts and the inventory list query NYC Open Data on demand (no local cache).
 * The analysis journey section reads a snapshot JSON (see notebooks/).
 *
 * Public static site (Vercel):
 *   Built with VITE_STATIC_SNAPSHOT=true via scripts/update-snapshot.sh.
 *   Live inventory/charts/AI are hidden; Analysis journey + key insight remain.
 *
 * “Jump to key insight” (top of page):
 *   Smooth-scrolls to #data-insight — the mold & moisture vs pests section.
 *   If that section is missing, re-run notebooks/run_final_insight.py.
 *
 * “Back to top” (bottom-right):
 *   Appears after you scroll down; returns to the top of the page.
 */

import { useEffect, useMemo, useState } from 'react'
import AnalysisPanel from './AnalysisPanel'
import ConcentrationJourney from './ConcentrationJourney'
import StatsDashboard from './StatsDashboard'
import {
  STATIC_LOCAL_ONLY_NOTE,
  fetchSodaFilterOptions,
  fetchSodaStatus,
  fetchSodaViolations,
  isStaticSnapshot,
} from './api'
import './App.css'

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 200]
const BACK_TO_TOP_AFTER_PX = 480

// Fallback if the API has not returned columns yet (same order as the dataset)
const FALLBACK_COLUMNS = [
  'violationid',
  'buildingid',
  'registrationid',
  'boroid',
  'boro',
  'housenumber',
  'lowhousenumber',
  'highhousenumber',
  'streetname',
  'streetcode',
  'zip',
  'apartment',
  'story',
  'block',
  'lot',
  'class',
  'inspectiondate',
  'approveddate',
  'originalcertifybydate',
  'originalcorrectbydate',
  'newcertifybydate',
  'newcorrectbydate',
  'certifieddate',
  'ordernumber',
  'novid',
  'novdescription',
  'novissueddate',
  'currentstatusid',
  'currentstatus',
  'currentstatusdate',
]

// Friendlier header labels for a few common fields; others use the raw name
const COLUMN_LABELS = {
  violationid: 'Violation ID',
  buildingid: 'Building ID',
  registrationid: 'Registration ID',
  boroid: 'Borough ID',
  boro: 'Borough',
  housenumber: 'House #',
  lowhousenumber: 'Low House #',
  highhousenumber: 'High House #',
  streetname: 'Street',
  streetcode: 'Street Code',
  zip: 'ZIP',
  apartment: 'Apartment',
  story: 'Story',
  block: 'Block',
  lot: 'Lot',
  class: 'Class',
  inspectiondate: 'Inspection Date',
  approveddate: 'Approved Date',
  originalcertifybydate: 'Orig. Certify By',
  originalcorrectbydate: 'Orig. Correct By',
  newcertifybydate: 'New Certify By',
  newcorrectbydate: 'New Correct By',
  certifieddate: 'Certified Date',
  ordernumber: 'Order #',
  novid: 'NOV ID',
  novdescription: 'NOV Description',
  novissueddate: 'NOV Issued',
  currentstatusid: 'Status ID',
  currentstatus: 'Current Status',
  currentstatusdate: 'Status Date',
}

// Wider columns for long text; everything else gets a compact default
const WIDE_COLUMNS = new Set(['novdescription', 'streetname', 'currentstatus'])

function columnLabel(key) {
  return COLUMN_LABELS[key] || key
}

function columnWidth(key) {
  if (key === 'novdescription') return '22rem'
  if (WIDE_COLUMNS.has(key)) return '12rem'
  if (key.endsWith('date') || key.endsWith('id')) return '9rem'
  return '8rem'
}

function formatCell(key, value) {
  // Always show a placeholder so blank columns still take space in the list
  if (value === null || value === undefined || String(value).trim() === '') {
    return '—'
  }
  // Shorten ISO timestamps to YYYY-MM-DD for readability
  if (key.endsWith('date') && String(value).includes('T')) {
    return String(value).slice(0, 10)
  }
  return String(value)
}

function App() {
  const staticMode = isStaticSnapshot()

  // ---- Toolbar state -------------------------------------------------------
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [boro, setBoro] = useState('')
  const [violationClass, setViolationClass] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState('inspectiondate')
  const [order, setOrder] = useState('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  // ---- Backend data --------------------------------------------------------
  const [filterOptions, setFilterOptions] = useState({
    boro: [],
    class: [],
    currentstatus: [],
  })
  const [cacheStatus, setCacheStatus] = useState(null)
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(!staticMode)
  const [error, setError] = useState('')
  const [showBackToTop, setShowBackToTop] = useState(false)

  // Debounce search so we do not query on every keystroke
  useEffect(() => {
    if (staticMode) return undefined
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput, staticMode])

  useEffect(() => {
    if (staticMode) return undefined
    fetchSodaFilterOptions()
      .then(setFilterOptions)
      .catch(() => {})
    fetchSodaStatus()
      .then(setCacheStatus)
      .catch(() => setCacheStatus(null))
  }, [staticMode])

  useEffect(() => {
    if (staticMode) return undefined
    let cancelled = false
    setLoading(true)
    setError('')

    fetchSodaViolations({
      search,
      boro,
      class: violationClass,
      status,
      sort,
      order,
      page,
      page_size: pageSize,
    })
      .then((data) => {
        if (!cancelled) {
          setPayload(data)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message)
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [search, boro, violationClass, status, sort, order, page, pageSize, staticMode])

  // Show the floating Back-to-top control after the visitor scrolls down
  useEffect(() => {
    function onScroll() {
      setShowBackToTop(window.scrollY > BACK_TO_TOP_AFTER_PX)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  function handleSort(columnKey) {
    if (sort === columnKey) {
      setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(columnKey)
      setOrder('asc')
    }
    setPage(1)
  }

  function clearFilters() {
    setSearchInput('')
    setSearch('')
    setBoro('')
    setViolationClass('')
    setStatus('')
    setSort('inspectiondate')
    setOrder('desc')
    setPage(1)
  }

  /**
   * Scroll the page down to the mold-vs-pests key insight.
   * The target element id is set in ConcentrationJourney.jsx.
   */
  function jumpToKeyInsight() {
    const el = document.getElementById('data-insight')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    // Section not on the page yet — usually means the analysis JSON needs a refresh
    window.alert(
      'Key insight section is not available yet. From notebooks/, run: python run_final_insight.py — then reload this page (and refresh snapshot/ for Vercel).',
    )
  }

  /** Docs-style control: return to the top of the page. */
  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const results = payload?.results || []
  const totalPages = payload?.total_pages || 0
  const matchCount = payload?.count || 0

  // Use every column from the API; fall back to the known full SODA set
  const columns = useMemo(() => {
    if (payload?.columns?.length) return payload.columns
    return FALLBACK_COLUMNS
  }, [payload])

  const gridTemplate = useMemo(
    () => columns.map((key) => columnWidth(key)).join(' '),
    [columns],
  )

  return (
    <div className="app-shell">
      <header className="topbar" id="page-top">
        <div>
          <p className="brand">NYC Open HPD Violation</p>
          <h1>{staticMode ? 'Open violations analysis' : 'Violation inventory'}</h1>
        </div>
        <div className="topbar-meta">
          {/*
            Primary CTA for first-time visitors: skip the long analysis journey
            and land on the main mold & moisture vs pests finding.
          */}
          <div className="jump-insight-block">
            <button
              type="button"
              className="jump-insight-btn"
              onClick={jumpToKeyInsight}
            >
              Jump to key insight
            </button>
            <p className="jump-insight-hint">
              Skip the analysis steps — go straight to the main finding
            </p>
          </div>
          {staticMode ? (
            <span className="pill muted">Public static snapshot</span>
          ) : cacheStatus?.api_ready ? (
            <span className="pill ok">
              {(cacheStatus.remote_rows ?? 0).toLocaleString()} live rows
            </span>
          ) : (
            <span className="pill warn">
              {cacheStatus?.error ? 'SODA API unreachable' : 'Checking SODA API…'}
            </span>
          )}
          {!staticMode && (
            <>
              <span className="pill muted">
                live SODA · {cacheStatus?.dataset_id || 'csn4-vhvf'}
              </span>
              <span className="pill muted">{columns.length} columns</span>
            </>
          )}
        </div>
      </header>

      {staticMode && (
        <p className="static-banner" role="note">
          {STATIC_LOCAL_ONLY_NOTE}
        </p>
      )}

      {/* Live SODA overview charts — local only; static site shows a short note */}
      <StatsDashboard />

      {/* Building concentration analysis journey (works on static + local) */}
      <ConcentrationJourney />

      {/* Live inventory + AI — local development only */}
      {!staticMode && (
        <>
          <section className="toolbar" aria-label="List controls">
            <label className="field grow">
              <span>Search</span>
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="ID, street, ZIP, apartment, description…"
              />
            </label>

            <label className="field">
              <span>Borough</span>
              <select
                value={boro}
                onChange={(e) => {
                  setBoro(e.target.value)
                  setPage(1)
                }}
              >
                <option value="">All</option>
                {filterOptions.boro.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Class</span>
              <select
                value={violationClass}
                onChange={(e) => {
                  setViolationClass(e.target.value)
                  setPage(1)
                }}
              >
                <option value="">All</option>
                {filterOptions.class.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="field wide">
              <span>Status</span>
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value)
                  setPage(1)
                }}
              >
                <option value="">All</option>
                {filterOptions.currentstatus.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Rows</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPage(1)
                }}
              >
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>
                    {size} / page
                  </option>
                ))}
              </select>
            </label>

            <button type="button" className="ghost-btn" onClick={clearFilters}>
              Reset
            </button>
          </section>

          <section className="inventory" aria-label="Violation list">
            <div className="inventory-status">
              <p>
                {loading
                  ? 'Loading…'
                  : `${matchCount.toLocaleString()} matching items · ${columns.length} columns`}
              </p>
              {error && <p className="error-text">{error}</p>}
              {payload?.message && <p className="error-text">{payload.message}</p>}
            </div>

            <div className="list-frame">
              <div className="list-scroll">
                <div
                  className="list-header"
                  style={{ gridTemplateColumns: gridTemplate }}
                  role="row"
                >
                  {columns.map((key) => {
                    const isActive = sort === key
                    const arrow = !isActive ? '' : order === 'asc' ? ' ↑' : ' ↓'
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`col-head ${isActive ? 'active' : ''}`}
                        onClick={() => handleSort(key)}
                        title={`Sort by ${key}`}
                      >
                        {columnLabel(key)}
                        {arrow}
                      </button>
                    )
                  })}
                </div>

                <ul className="item-list">
                  {!loading && results.length === 0 && (
                    <li className="empty-row">No items match the current filters.</li>
                  )}

                  {results.map((row) => (
                    <li
                      key={
                        row.violationid ||
                        `${row.buildingid}-${row.novid}-${row.ordernumber}`
                      }
                      className="item-row"
                      style={{ gridTemplateColumns: gridTemplate }}
                    >
                      {columns.map((key) => {
                        const display = formatCell(key, row[key])
                        const isClass = key === 'class' && display !== '—'
                        return (
                          <span
                            key={key}
                            className={[
                              'cell',
                              key.endsWith('id') || key.endsWith('date') ? 'mono' : '',
                              key === 'novdescription' ? 'desc-cell' : '',
                              isClass ? `class-badge class-${display}` : '',
                            ]
                              .filter(Boolean)
                              .join(' ')}
                            title={
                              display === '—'
                                ? `${key}: (blank)`
                                : String(row[key] ?? '')
                            }
                          >
                            {display}
                          </span>
                        )
                      })}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="pager">
              <button
                type="button"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </button>
              <span>
                Page {page}
                {totalPages ? ` of ${totalPages.toLocaleString()}` : ''}
                {' · '}
                {pageSize} rows
              </span>
              <button
                type="button"
                disabled={loading || !totalPages || page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </section>

          <AnalysisPanel
            filters={{
              search,
              boro,
              class: violationClass,
              status,
            }}
          />
        </>
      )}

      {/* Floating control — same idea as docs sites; appears after scrolling */}
      {showBackToTop && (
        <button
          type="button"
          className="back-to-top-btn"
          onClick={scrollToTop}
          aria-label="Back to top of page"
        >
          Back to top
        </button>
      )}
    </div>
  )
}

export default App
