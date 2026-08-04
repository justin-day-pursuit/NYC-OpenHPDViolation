/**
 * Browser-tab session helpers for AI analysis.
 *
 * Plain English:
 *   Each browser tab gets one id. The FIRST analysis request in that tab
 *   sends the dataset summary to Gemini. Later requests only send the new
 *   prompt, which saves tokens and network traffic.
 *
 * How to reset (if answers seem stuck on old data):
 *   Open DevTools → Application → Session Storage → clear keys starting with
 *   "hpdAi", then refresh the page. Or just open a new tab.
 */

const SESSION_ID_KEY = 'hpdAiSessionId'
const DATA_SENT_KEY = 'hpdAiDataSent'

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
 * Has this tab already sent its one-time dataset pack?
 */
export function hasSentAnalysisData() {
  return sessionStorage.getItem(DATA_SENT_KEY) === '1'
}

/**
 * Remember that the dataset pack was delivered for this tab.
 */
export function markAnalysisDataSent() {
  sessionStorage.setItem(DATA_SENT_KEY, '1')
}
