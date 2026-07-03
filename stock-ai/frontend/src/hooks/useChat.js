import { useState, useCallback, useRef } from 'react'
import axios from 'axios'
import { sendMessage } from '../services/api'

export const useChat = () => {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastQuery, setLastQuery] = useState(null)

  // Controller reference to cancel previous requests (AbortController)
  const abortControllerRef = useRef(null)

  const sendQuestion = useCallback(async (question) => {
    if (!question.trim()) return

    // 1. Cancel previous pending request if a new question is asked
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    // 2. Setup a new AbortController
    const controller = new AbortController()
    abortControllerRef.current = controller

    const userMessage = { id: Date.now(), role: 'user', content: question }
    setMessages(prev => [...prev, userMessage])
    setLoading(true)
    setError(null)
    setLastQuery(question)

    try {
      const data = await sendMessage(question, controller.signal)
      
      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: data.answer,
        intent: data.intent,
        companies: data.companies || [],
        metrics: data.metrics || [],
        financial_data: data.financial_data || {},
        documents: data.documents || [],
        news: data.news || [],
        sources: data.sources || [],
        warnings: data.warnings || [],
      }
      setMessages(prev => [...prev, assistantMessage])
    } catch (err) {
      // 3. Gracefully skip state updates if request was cancelled intentionally
      if (axios.isCancel(err)) {
        console.log(`Request for query "${question}" was cancelled.`)
        return
      }

      // 4. Present friendly message for timeout errors
      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      let userFriendlyMsg = 'Something went wrong. Please try again.'

      if (isTimeout) {
        userFriendlyMsg = 'The request is taking longer than expected. Please try again in a moment.'
      } else {
        userFriendlyMsg = err.response?.data?.detail || err.message || 'Something went wrong.'
      }

      // Log detailed error in console only, not in user viewport
      console.error("Detailed error captured during sendQuestion:", err)
      setError(userFriendlyMsg)
    } finally {
      // Only reset loading state if this controller wasn't aborted/superseded
      if (abortControllerRef.current === controller) {
        setLoading(false)
      }
    }
  }, [])

  const retryLastQuery = useCallback(() => {
    if (lastQuery) {
      sendQuestion(lastQuery)
    }
  }, [lastQuery, sendQuestion])

  const newChat = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setMessages([])
    setError(null)
    setLastQuery(null)
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return { 
    messages, 
    loading, 
    error, 
    sendQuestion, 
    retryLastQuery, 
    newChat, 
    clearError 
  }
}
