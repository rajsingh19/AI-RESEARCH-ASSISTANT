import { useState, useCallback, useRef, useEffect } from 'react'
import axios from 'axios'
import { useAuth } from '../context/AuthContext'
import {
  getConversations,
  getConversationDetails,
  createConversation,
  deleteConversation,
  sendConversationMessageStream
} from '../services/api'

export const useChat = () => {
  const { token } = useAuth()
  const [conversations, setConversations] = useState([])
  const [selectedConversationId, setSelectedConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastQuery, setLastQuery] = useState(null)

  const abortControllerRef = useRef(null)

  // Re-initialize whenever the user logs in (token changes)
  useEffect(() => {
    if (!token) {
      setConversations([])
      setSelectedConversationId(null)
      setMessages([])
      return
    }

    const initializeChat = async () => {
      try {
        const list = await getConversations()
        setConversations(list)
        if (list.length > 0) {
          await selectConversation(list[0].id)
        } else {
          await triggerNewChat()
        }
      } catch (err) {
        console.error('Failed to initialize conversation list:', err)
      }
    }
    initializeChat()
  }, [token])

  const selectConversation = useCallback(async (id) => {
    if (abortControllerRef.current) abortControllerRef.current.abort()
    setLoading(true)
    setError(null)
    setLastQuery(null)
    setSelectedConversationId(id)
    try {
      const details = await getConversationDetails(id)
      setMessages(details.messages || [])
    } catch (err) {
      console.error(`Failed to load conversation id=${id}:`, err)
      setError('Failed to load chat history. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  const triggerNewChat = useCallback(async () => {
    if (abortControllerRef.current) abortControllerRef.current.abort()
    setError(null)
    setLastQuery(null)
    setLoading(true)
    try {
      const newConv = await createConversation()
      setSelectedConversationId(newConv.id)
      setMessages([])
      const list = await getConversations()
      setConversations(list)
    } catch (err) {
      console.error('Failed to create new conversation:', err)
      setError('Failed to start new chat session.')
    } finally {
      setLoading(false)
    }
  }, [])

  const deleteChat = useCallback(async (id) => {
    try {
      await deleteConversation(id)
      const list = await getConversations()
      setConversations(list)
      if (selectedConversationId === id) {
        if (list.length > 0) await selectConversation(list[0].id)
        else await triggerNewChat()
      }
    } catch (err) {
      console.error(`Failed to delete conversation id=${id}:`, err)
    }
  }, [selectedConversationId, selectConversation, triggerNewChat])

  const cancelRequest = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
      setLoading(false)
      setMessages(prev => prev.map(msg =>
        msg.loading ? { ...msg, loading: false, content: msg.content + ' [Generation Interrupted]' } : msg
      ))
    }
  }, [])

  const sendQuestion = useCallback(async (question) => {
    if (!question.trim()) return

    if (abortControllerRef.current) abortControllerRef.current.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

    let currentId = selectedConversationId
    if (!currentId) {
      try {
        const newConv = await createConversation()
        currentId = newConv.id
        setSelectedConversationId(currentId)
      } catch (err) {
        setError('Failed to start conversation session.')
        return
      }
    }

    const userMessage = { id: Date.now(), role: 'user', content: question }
    const assistantMsgId = Date.now() + 1
    const emptyAssistantMessage = { id: assistantMsgId, role: 'assistant', content: '', loading: true }

    setMessages(prev => [...prev, userMessage, emptyAssistantMessage])
    setLoading(true)
    setError(null)
    setLastQuery(question)

    try {
      await sendConversationMessageStream(
        currentId,
        question,
        (token) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMsgId ? { ...msg, content: msg.content + token } : msg
          ))
        },
        (metadata) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  loading: false,
                  intent: metadata.intent,
                  companies: metadata.companies || [],
                  metrics: metadata.metrics || [],
                  financial_data: metadata.financial_data || {},
                  documents: metadata.documents || [],
                  news: metadata.news || [],
                  sources: metadata.sources || [],
                  warnings: metadata.warnings || [],
                }
              : msg
          ))
        },
        controller.signal
      )

      const list = await getConversations()
      setConversations(list)
    } catch (err) {
      if (err.name === 'AbortError' || axios.isCancel(err)) return

      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      const userFriendlyMsg = isTimeout
        ? 'The request is taking longer than expected. Please try again.'
        : err.response?.data?.detail || err.message || 'Something went wrong.'

      setError(userFriendlyMsg)
      setMessages(prev => prev.filter(msg => msg.id !== assistantMsgId))
    } finally {
      if (abortControllerRef.current === controller) setLoading(false)
    }
  }, [selectedConversationId])

  const retryLastQuery = useCallback(() => {
    if (lastQuery) sendQuestion(lastQuery)
  }, [lastQuery, sendQuestion])

  const clearError = useCallback(() => setError(null), [])

  return {
    conversations,
    selectedConversationId,
    messages,
    loading,
    error,
    sendQuestion,
    retryLastQuery,
    newChat: triggerNewChat,
    selectConversation,
    deleteChat,
    cancelRequest,
    clearError,
  }
}
