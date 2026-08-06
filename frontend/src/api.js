/**
 * Small helpers for talking to the Django backend.
 *
 * Local development:
 *   Leave VITE_DJANGO_API_URL empty (or unset) so requests use "/api/..."
 *   and Vite proxies them to Django (see vite.config.js).
 *
 * Public static site (Vercel snapshot):
 *   Built with VITE_STATIC_SNAPSHOT=true — live API calls are disabled.
 *   The Analysis journey still works from /analysis/*.json.
 *
 * Never put secret API keys in VITE_* variables.
 */

// Base URL for Django. Empty string = same origin (works with the Vite proxy).
const RAW_API_BASE = import.meta.env.VITE_DJANGO_API_URL || ''
const API_BASE = String(RAW_API_BASE).replace(/\/+$/, '')

/**
 * True when this build is the public static snapshot (no Django on Vercel).
 * Set by scripts/update-snapshot.sh via VITE_STATIC_SNAPSHOT=true.
 */
export function isStaticSnapshot() {
  const flag = import.meta.env.VITE_STATIC_SNAPSHOT
  return flag === true || flag === 'true' || flag === '1'
}

/**
 * True when the UI should call the live Django API.
 * Static snapshot builds always return false.
 */
export function isApiConfigured() {
  if (isStaticSnapshot()) return false
  // Local dev: empty base is OK (Vite proxy). Production non-snapshot
  // builds would need an absolute VITE_DJANGO_API_URL if used that way.
  return true
}

/** Plain-English note for sections that need Django locally. */
export const STATIC_LOCAL_ONLY_NOTE =
  'Live inventory, overview charts, and AI run in local development (Django + AI service). This public page serves the Analysis journey and key insight from a static data snapshot.'

/**
 * GET /api/health/ — quick check that Django is reachable.
 */
export async function fetchHealth() {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/health/`)
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status})`)
  }
  return response.json()
}

/**
 * GET /api/soda-violations/ — filtered / sorted / paged LIVE SODA rows.
 *
 * @param {object} params filter + sort + page options
 */
export async function fetchSodaViolations(params = {}) {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, value)
    }
  })
  const response = await fetch(`${API_BASE}/api/soda-violations/?${query}`)
  if (!response.ok) {
    throw new Error(`Could not load SODA violations (${response.status})`)
  }
  return response.json()
}

/**
 * GET /api/soda-violations/filters/ — dropdown option lists
 */
export async function fetchSodaFilterOptions() {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/soda-violations/filters/`)
  if (!response.ok) {
    throw new Error(`Could not load filter options (${response.status})`)
  }
  return response.json()
}

/**
 * GET /api/soda-violations/status/ — is the live SODA API reachable?
 */
export async function fetchSodaStatus() {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/soda-violations/status/`)
  if (!response.ok) {
    throw new Error(`Could not load SODA status (${response.status})`)
  }
  return response.json()
}

/**
 * GET /api/soda-violations/stats/ — live dashboard chart counts (no AI).
 *
 * Returns by_boro / by_class / by_currentstatus / by_month as
 * [{ name, value }, ...] ready for Recharts.
 *
 * Non-technical tip:
 *   If this fails, start Django and set SOCRATA_APP_TOKEN in the root .env.
 *   First load can take 1–3 minutes (remote aggregates).
 */
export async function fetchSodaStats() {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/soda-violations/stats/`)
  if (!response.ok) {
    throw new Error(`Could not load dashboard stats (${response.status})`)
  }
  return response.json()
}

/**
 * POST /api/ask-ai/ — send a question; Django forwards it to the FastAPI AI service.
 */
export async function askAi(question) {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/ask-ai/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || data.error || `AI request failed (${response.status})`)
  }
  return data
}

/**
 * POST /api/analyze/ — session-aware Gemini analysis with charts/tables.
 *
 * includeData should be true on the first ask in a tab, and again whenever
 * inventory filters change (so Gemini gets a fresh filtered summary).
 *
 * filters should match the inventory toolbar: { search, boro, class, status }.
 *
 * @param {{
 *   prompt: string,
 *   sessionId: string,
 *   includeData: boolean,
 *   filters?: { search?: string, boro?: string, class?: string, status?: string },
 * }} args
 */
export async function analyzeWithAi({ prompt, sessionId, includeData, filters = {} }) {
  if (!isApiConfigured()) {
    throw new Error(STATIC_LOCAL_ONLY_NOTE)
  }
  const response = await fetch(`${API_BASE}/api/analyze/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      session_id: sessionId,
      include_data: includeData,
      filters: {
        search: filters.search || '',
        boro: filters.boro || '',
        class: filters.class || '',
        status: filters.status || '',
      },
    }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(
      data.detail || data.error || `Analysis request failed (${response.status})`,
    )
  }
  return data
}
