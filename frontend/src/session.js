/**
 * Browser-tab session helpers for AI analysis.
 *
 * Plain English:
 *   Each browser tab gets one id. The FIRST analysis request in that tab
 *   (or the first ask after you change list filters) sends a dataset summary
 *   to Gemini. Later requests with the SAME filters only send the new prompt,
 *   which saves tokens and network traffic.
 *
 * How to reset (if answers seem stuck on old data):
 *   Open DevTools → Application → Session Storage → clear keys starting with
 *   "hpdAi", then refresh the page. Or just open a new tab.
 */

const SESSION_ID_KEY = 'hpdAiSessionId'
const DATA_SENT_KEY = 'hpdAiDataSent'
const FILTERS_KEY = 'hpdAiFiltersKey'

/**
 * Get (or create) a stable id for this browser tab.
 */
export function getAnalysisSessionId() {
  let id = sessionStorage.getItem(SESSION_ID_KEY)
  if (!id) {
    // crypto.randomUUID is built into modern browsers
    id = crypto.randomUUID()
    sessionStorage.setItem(SESSION_ID_KEY, id)
  }
  return id
}

/**
 * Turn inventory filters into a short comparable string.
 * Used to detect "filters changed → need a fresh AI data pack".
 */
export function filtersToKey(filters = {}) {
  return JSON.stringify({
    search: String(filters.search || '').trim(),
    boro: String(filters.boro || '').trim(),
    class: String(filters.class || '').trim(),
    status: String(filters.status || '').trim(),
  })
}

/**
 * Has this tab already sent a dataset pack for the given filters?
 */
export function hasSentAnalysisData(filters = {}) {
  if (sessionStorage.getItem(DATA_SENT_KEY) !== '1') return false
  return sessionStorage.getItem(FILTERS_KEY) === filtersToKey(filters)
}

/**
 * Remember that a dataset pack was delivered for these filters.
 */
export function markAnalysisDataSent(filters = {}) {
  sessionStorage.setItem(DATA_SENT_KEY, '1')
  sessionStorage.setItem(FILTERS_KEY, filtersToKey(filters))
}
