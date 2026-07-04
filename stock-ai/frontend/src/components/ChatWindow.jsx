import { useEffect, useRef } from 'react'
import { StopCircle } from 'lucide-react'
import Message from './Message'
import LoadingMessage from './LoadingMessage'
import ChatInput from './ChatInput'

const CONTEXT_CHIPS = [
  'Compare with Infosys',
  'What are the key risks?',
  'Revenue growth over last 5 years',
  'Dividend history',
]

export default function ChatWindow({ 
  messages, 
  loading, 
  error, 
  onSend, 
  onRetry, 
  onClearError,
  onCancel
}) {
  const bottomRef = useRef(null)
  const isEmpty = messages.length === 0

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'auto' })
  }, [messages])

  return (
    <div className="flex flex-col flex-1 min-w-0 h-full overflow-hidden">
      {/* Chat header */}
      <div className="px-6 py-4 border-b border-[#1F2937] flex-shrink-0">
        <h1 className="text-xl font-bold text-indigo-400">Stock AI Assistant</h1>
        <p className="text-sm text-gray-400 mt-0.5">Ask any question about stocks, companies, results, news and more.</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {isEmpty ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">Start a conversation below.</p>
          </div>
        ) : (
          <>
            {messages.map(msg => <Message key={msg.id} message={msg} />)}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Error banner with retry option */}
      {error && (
        <div className="mx-6 mb-2 flex items-center justify-between gap-3 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400">
          <span>⚠ {error}</span>
          <div className="flex items-center gap-2.5 flex-shrink-0">
            {onRetry && (
              <button 
                onClick={onRetry} 
                className="px-3 py-1 bg-red-500/20 hover:bg-red-500/35 border border-red-500/30 rounded-lg text-xs font-semibold text-red-300 hover:text-white transition-all"
              >
                Retry
              </button>
            )}
            <button onClick={onClearError} className="text-xs underline text-gray-400 hover:text-white">Dismiss</button>
          </div>
        </div>
      )}

      {/* Context chips — shown after first response */}
      {!isEmpty && !loading && (
        <div className="px-6 pb-2 flex flex-wrap gap-2">
          {CONTEXT_CHIPS.map(chip => (
            <button
              key={chip}
              onClick={() => onSend(chip)}
              className="px-4 py-1.5 rounded-full text-sm border border-[#374151] text-gray-300 hover:border-indigo-500/50 hover:text-indigo-300 bg-[#111827] transition-all"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* Cancel request button overlay while streaming */}
      {loading && onCancel && (
        <div className="flex justify-center mb-2">
          <button
            onClick={onCancel}
            className="flex items-center gap-2 px-4 py-2 bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 rounded-xl text-sm font-semibold text-red-400 hover:text-white transition-all shadow-md animate-pulse"
          >
            <StopCircle size={15} />
            Stop Generating
          </button>
        </div>
      )}

      <ChatInput onSend={onSend} loading={loading} />
    </div>
  )
}
