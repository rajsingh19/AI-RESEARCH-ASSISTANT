import { useState, useCallback, useRef, useEffect } from 'react'
import axios from 'axios'
import {
  getConversations,
  getConversationDetails,
  createConversation,
  deleteConversation,
  sendConversationMessageStream
} from '../services/api'

export const useChat = () => {
  const [conversations, setConversations] = useState([])
  const [selectedConversationId, setSelectedConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastQuery, setLastQuery] = useState(null)

  // Controller reference to cancel previous requests (AbortController)
  const abortControllerRef = useRef(null)

  // Load initial conversations on mount
  useEffect(() => {
    const initializeChat = async () => {
      try {
        const list = await getConversations()
        setConversations(list)
        if (list.length > 0) {
          // Select the most recent active conversation
          await selectConversation(list[0].id)
        } else {
          // Start with a clean new chat session if database is empty
          await triggerNewChat()
        }
      } catch (err) {
        console.error("Failed to initialize conversation list on mount:", err)
      }
    }
    initializeChat()
  }, [])

  // Switch to another conversation
  const selectConversation = useCallback(async (id) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setLoading(true)
    setError(null)
    setLastQuery(null)
    setSelectedConversationId(id)
    try {
      const details = await getConversationDetails(id)
      setMessages(details.messages || [])
    } catch (err) {
      console.error(`Failed to load conversation details for id=${id}:`, err)
      setError("Failed to load chat history. Please try again.")
    } finally {
      setLoading(false)
    }
  }, [])

  // Start a fresh empty new chat session
  const triggerNewChat = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setError(null)
    setLastQuery(null)
    setLoading(true)
    try {
      const newConv = await createConversation()
      setSelectedConversationId(newConv.id)
      setMessages([])
      
      // Refresh list to show the new empty chat row
      const list = await getConversations()
      setConversations(list)
    } catch (err) {
      console.error("Failed to trigger new conversation session:", err)
      setError("Failed to start new chat session.")
    } finally {
      setLoading(false)
    }
  }, [])

  // Delete a conversation thread
  const deleteChat = useCallback(async (id) => {
    try {
      await deleteConversation(id)
      const list = await getConversations()
      setConversations(list)
      
      // If we deleted the active conversation, switch focus
      if (selectedConversationId === id) {
        if (list.length > 0) {
          await selectConversation(list[0].id)
        } else {
          await triggerNewChat()
        }
      }
    } catch (err) {
      console.error(`Failed to delete conversation id=${id}:`, err)
    }
  }, [selectedConversationId, selectConversation, triggerNewChat])

  // Cancel running stream generation
  const cancelRequest = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
      setLoading(false)
      // Stop typing state indicators
      setMessages(prev => prev.map(msg => {
        if (msg.loading) {
          return { ...msg, loading: false, content: msg.content + " [Generation Interrupted]" }
        }
        return msg
      }))
    }
  }, [])

  // Send a user question
  const sendQuestion = useCallback(async (question) => {
    if (!question.trim()) return

    // 1. Cancel previous pending request if a new question is asked
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    // 2. Setup a new AbortController
    const controller = new AbortController()
    abortControllerRef.current = controller

    let currentId = selectedConversationId
    if (!currentId) {
      try {
        const newConv = await createConversation()
        currentId = newConv.id
        setSelectedConversationId(currentId)
      } catch (err) {
        setError("Failed to start conversation session.")
        return
      }
    }

    const userMessage = { id: Date.now(), role: 'user', content: question }
    const assistantMsgId = Date.now() + 1
    const emptyAssistantMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      loading: true // Shows cursor/spinner until first token arrives
    }

    setMessages(prev => [...prev, userMessage, emptyAssistantMessage])
    setLoading(true)
    setError(null)
    setLastQuery(question)

    try {
      await sendConversationMessageStream(
        currentId,
        question,
        (token) => {
          // Append streamed tokens to current message
          setMessages(prev => prev.map(msg => {
            if (msg.id === assistantMsgId) {
              return {
                ...msg,
                content: msg.content + token
              }
            }
            return msg
          }))
        },
        (metadata) => {
          // Append citation sources and formatting at the end
          setMessages(prev => prev.map(msg => {
            if (msg.id === assistantMsgId) {
              return {
                ...msg,
                loading: false, // Turn off active cursor
                intent: metadata.intent,
                companies: metadata.companies || [],
                metrics: metadata.metrics || [],
                financial_data: metadata.financial_data || {},
                documents: metadata.documents || [],
                news: metadata.news || [],
                sources: metadata.sources || [],
                warnings: metadata.warnings || [],
              }
            }
            return msg
          }))
        },
        controller.signal
      )
      
      // 3. Refresh conversations list to update dynamic title & sorting updatedAt order
      const list = await getConversations()
      setConversations(list)
    } catch (err) {
      // Gracefully handle abort triggers
      if (err.name === 'AbortError' || axios.isCancel(err)) {
        console.log(`Stream generation for query "${question}" was cancelled.`)
        return
      }

      const isTimeout = err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')
      let userFriendlyMsg = 'Something went wrong. Please try again.'

      if (isTimeout) {
        userFriendlyMsg = 'The request is taking longer than expected. Please try again in a moment.'
      } else {
        userFriendlyMsg = err.response?.data?.detail || err.message || 'Something went wrong.'
      }

      console.error("Detailed error captured during sendQuestion:", err)
      setError(userFriendlyMsg)
      
      // Remove empty assistant message on fetch failure
      setMessages(prev => prev.filter(msg => msg.id !== assistantMsgId))
    } finally {
      if (abortControllerRef.current === controller) {
        setLoading(false)
      }
    }
  }, [selectedConversationId])

  const retryLastQuery = useCallback(() => {
    if (lastQuery) {
      sendQuestion(lastQuery)
    }
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
    clearError
  }
}
