/**
 * Small helpers for talking to the Django backend.
 *
 * Change VITE_DJANGO_API_URL in frontend/.env.local if Django is not on port 8000.
 * During `npm run dev`, you can also use relative paths like "/api/..." because
 * vite.config.js proxies /api to Django.
 */

// Base URL for Django. Empty string = same origin (works with the Vite proxy).
const API_BASE = import.meta.env.VITE_DJANGO_API_URL || ''

/**
 * GET /api/health/ — quick check that Django is reachable.
 */
export async function fetchHealth() {
  const response = await fetch(`${API_BASE}/api/health/`)
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status})`)
  }
  return response.json()
}

/**
 * GET /api/violations/ — list stored violation records.
 */
export async function fetchViolations() {
  const response = await fetch(`${API_BASE}/api/violations/`)
  if (!response.ok) {
    throw new Error(`Could not load violations (${response.status})`)
  }
  return response.json()
}

/**
 * POST /api/ask-ai/ — send a question; Django forwards it to the FastAPI AI service.
 */
export async function askAi(question) {
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
