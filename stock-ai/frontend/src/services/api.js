import axios from 'axios'

const timeoutMs = parseInt(import.meta.env.VITE_API_TIMEOUT) || 60000

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
  timeout: timeoutMs,
})

// Attach JWT token from localStorage on every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

export const getConversations = async () => {
  const { data } = await api.get('/api/conversations')
  return data
}

export const getConversationDetails = async (id) => {
  const { data } = await api.get(`/api/conversations/${id}`)
  return data
}

export const createConversation = async (id = null, title = 'New Chat') => {
  const { data } = await api.post('/api/conversations', { id, title })
  return data
}

export const deleteConversation = async (id) => {
  const { data } = await api.delete(`/api/conversations/${id}`)
  return data
}

export const sendConversationMessage = async (conversationId, question, signal) => {
  let retries = 3
  let delay = 1000

  while (retries >= 0) {
    try {
      const { data } = await api.post(
        `/api/conversations/${conversationId}/messages`,
        { content: question },
        { signal }
      )
      return data
    } catch (err) {
      if (axios.isCancel(err)) throw err

      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      const isNetworkError = err.message?.toLowerCase().includes('network error') || !err.response

      if (retries > 0 && (isTimeout || isNetworkError)) {
        await new Promise(resolve => setTimeout(resolve, delay))
        retries--
        delay *= 2
      } else {
        throw err
      }
    }
  }
}

export const sendConversationMessageStream = async (conversationId, question, onChunk, onMetadata, signal) => {
  const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const token = localStorage.getItem('token')

  const response = await fetch(`${baseURL}/api/conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content: question }),
    signal,
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(errorText || `HTTP error! status: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let isMetadataEvent = false

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue

        if (trimmed.startsWith('event: metadata')) {
          isMetadataEvent = true
          continue
        }

        if (trimmed.startsWith('data: ')) {
          const rawData = trimmed.slice(6)
          try {
            const parsed = JSON.parse(rawData)
            if (isMetadataEvent) {
              onMetadata(parsed)
              isMetadataEvent = false
            } else if (parsed && parsed.token !== undefined) {
              onChunk(parsed.token)
            }
          } catch (e) {
            console.error('Failed to parse SSE data block:', e)
          }
          isMetadataEvent = false
        }
      }
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      console.log('Stream reading aborted by client.')
    } else {
      throw error
    }
  } finally {
    reader.releaseLock()
  }
}

export const healthCheck = async () => {
  const { data } = await api.get('/')
  return data
}

export default api
