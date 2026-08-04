/**
 * Inventory-style Open HPD Violations browser.
 *
 * Layout is meant to feel like a database / inventory list:
 *  - toolbar with search, filters, sort, and page size
 *  - dense scrollable item list with sortable column headers
 *  - dynamic page sizing (how many rows fit / you choose to show)
 */

import { useEffect, useMemo, useState } from 'react'
import {
  fetchSodaFilterOptions,
  fetchSodaStatus,
  fetchSodaViolations,
} from './api'
import './App.css'

// Sortable columns shown as inventory list headers
const COLUMNS = [
  { key: 'violationid', label: 'ID', width: '7rem' },
  { key: 'class', label: 'Class', width: '4.5rem' },
  { key: 'boro', label: 'Borough', width: '7rem' },
  { key: 'address', label: 'Address', width: '1fr' },
  { key: 'zip', label: 'ZIP', width: '5rem' },
  { key: 'inspectiondate', label: 'Inspected', width: '7rem' },
  { key: 'currentstatus', label: 'Status', width: '1.2fr' },
]

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 200]

function formatDate(value) {
  if (!value) return '—'
  return String(value).slice(0, 10)
}

function formatAddress(row) {
  const street = [row.housenumber, row.streetname].filter(Boolean).join(' ')
  if (row.apartment) return `${street}, Apt ${row.apartment}`
  return street || '—'
}

function App() {
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Debounce search so we do not query on every keystroke
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    fetchSodaFilterOptions()
      .then(setFilterOptions)
      .catch(() => {})
    fetchSodaStatus()
      .then(setCacheStatus)
      .catch(() => setCacheStatus(null))
  }, [])

  useEffect(() => {
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
  }, [search, boro, violationClass, status, sort, order, page, pageSize])

  function handleSort(columnKey) {
    // "address" is a display column — sort by streetname underneath
    const apiColumn = columnKey === 'address' ? 'streetname' : columnKey
    if (sort === apiColumn) {
      setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(apiColumn)
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

  const results = payload?.results || []
  const totalPages = payload?.total_pages || 0
  const matchCount = payload?.count || 0

  const gridTemplate = useMemo(
    () => COLUMNS.map((col) => col.width).join(' '),
    [],
  )

  const activeSortKey = sort === 'streetname' ? 'address' : sort

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="brand">NYC Open HPD Violation</p>
          <h1>Violation inventory</h1>
        </div>
        <div className="topbar-meta">
          {cacheStatus?.cache_ready ? (
            <span className="pill ok">
              {cacheStatus.cached_rows?.toLocaleString()} rows cached
            </span>
          ) : (
            <span className="pill warn">Cache empty — run fetch_soda_violations</span>
          )}
          <span className="pill muted">dataset {cacheStatus?.dataset_id || 'csn4-vhvf'}</span>
        </div>
      </header>

      {/* Toolbar: search / filter / sort / page size */}
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

      {/* Inventory list container */}
      <section className="inventory" aria-label="Violation list">
        <div className="inventory-status">
          <p>
            {loading
              ? 'Loading…'
              : `${matchCount.toLocaleString()} matching items`}
          </p>
          {error && <p className="error-text">{error}</p>}
          {payload?.message && <p className="error-text">{payload.message}</p>}
        </div>

        <div className="list-frame">
          <div
            className="list-header"
            style={{ gridTemplateColumns: gridTemplate }}
            role="row"
          >
            {COLUMNS.map((col) => {
              const isActive = activeSortKey === col.key
              const arrow = !isActive ? '' : order === 'asc' ? ' ↑' : ' ↓'
              return (
                <button
                  key={col.key}
                  type="button"
                  className={`col-head ${isActive ? 'active' : ''}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}
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
                key={row.violationid || `${row.buildingid}-${row.novid}`}
                className="item-row"
                style={{ gridTemplateColumns: gridTemplate }}
              >
                <span className="mono" title={row.violationid}>
                  {row.violationid || '—'}
                </span>
                <span className={`class-badge class-${row.class || 'x'}`}>
                  {row.class || '—'}
                </span>
                <span>{row.boro || '—'}</span>
                <span className="address-cell" title={row.novdescription || ''}>
                  <strong>{formatAddress(row)}</strong>
                  <em>{row.novdescription || 'No description'}</em>
                </span>
                <span>{row.zip || '—'}</span>
                <span className="mono">{formatDate(row.inspectiondate)}</span>
                <span className="status-cell" title={row.currentstatus || ''}>
                  {row.currentstatus || '—'}
                </span>
              </li>
            ))}
          </ul>
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
    </div>
  )
}

export default App
