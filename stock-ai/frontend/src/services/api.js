import axios from 'axios'

const timeoutMs = parseInt(import.meta.env.VITE_API_TIMEOUT) || 60000;

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
  timeout: timeoutMs,
})

/**
 * Sends the question to the AI assistant backend with transient retry loops and AbortSignals.
 *
 * @param {string} question - User's prompt.
 * @param {AbortSignal} [signal] - Optional signal to cancel the request.
 */
export const sendMessage = async (question, signal) => {
  let retries = 3
  let delay = 1000

  while (retries >= 0) {
    try {
      const { data } = await api.post('/chat', { question }, { signal })
      return data
    } catch (err) {
      // 1. If the request was aborted/cancelled intentionally, propagate the error immediately
      if (axios.isCancel(err)) {
        throw err
      }

      // 2. Identify transient conditions (timeout or network error)
      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      const isNetworkError = err.message?.toLowerCase().includes('network error') || !err.response

      if (retries > 0 && (isTimeout || isNetworkError)) {
        console.warn(`Request failed due to ${isTimeout ? 'timeout' : 'network issue'}. Retrying in ${delay}ms... (${retries} attempts remaining)`)
        await new Promise(resolve => setTimeout(resolve, delay))
        retries--
        delay *= 2 // Exponential backoff scaling
      } else {
        // Log detailed error logs to client console, not to user-facing viewport
        console.error("Axios request failure details:", err)
        throw err
      }
    }
  }
}

export const healthCheck = async () => {
  const { data } = await api.get('/')
  return data
}

export default api
