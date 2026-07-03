import { useState, useRef } from 'react'
import { Send, AlertTriangle } from 'lucide-react'

export default function ChatInput({ onSend, loading }) {
  const [value, setValue] = useState('')
  const ref = useRef(null)

  const handleSend = () => {
    const trimmed = value.trim()
    if (!trimmed || loading) return
    onSend(trimmed)
    setValue('')
    if (ref.current) ref.current.style.height = 'auto'
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleInput = (e) => {
    setValue(e.target.value)
    if (ref.current) {
      ref.current.style.height = 'auto'
      ref.current.style.height = Math.min(ref.current.scrollHeight, 160) + 'px'
    }
  }

  return (
    <div className="px-6 py-4 flex-shrink-0">
      <div className="flex items-end gap-3 bg-[#1a2235] border border-[#2d3748] rounded-2xl px-4 py-3 focus-within:border-indigo-500/60 transition-colors">
        <textarea
          ref={ref}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about stocks, companies, results, news..."
          rows={1}
          disabled={loading}
          className="flex-1 bg-transparent text-gray-100 placeholder-gray-500 text-sm resize-none outline-none leading-relaxed disabled:opacity-50 min-h-[24px]"
        />
        <button
          onClick={handleSend}
          disabled={!value.trim() || loading}
          className="w-10 h-10 rounded-xl bg-indigo-600 hover:bg-indigo-500 flex items-center justify-center flex-shrink-0 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          ) : (
            <Send size={16} className="text-white" />
          )}
        </button>
      </div>
      <p className="text-center text-xs text-gray-500 mt-2 flex items-center justify-center gap-1.5">
        <AlertTriangle size={11} />
        AI-generated responses are for informational purposes only and not financial advice.
      </p>
    </div>
  )
}
