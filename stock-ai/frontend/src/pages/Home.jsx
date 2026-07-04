import { useState } from 'react'
import Sidebar from '../components/Sidebar'
import ChatWindow from '../components/ChatWindow'
import { useChat } from '../hooks/useChat'
import { ShieldAlert } from 'lucide-react'

export default function Home() {
  const { 
    conversations,
    selectedConversationId,
    messages, 
    loading, 
    error, 
    sendQuestion, 
    retryLastQuery, 
    newChat, 
    selectConversation,
    deleteChat,
    cancelRequest,
    clearError 
  } = useChat()
  const [showDisclaimer, setShowDisclaimer] = useState(false)

  return (
    <div className="flex flex-col h-screen bg-[#0B1120] overflow-hidden">
      {/* Top Navbar */}
      <header className="flex items-center justify-between px-5 py-3 bg-[#0d1526] border-b border-[#1F2937] z-10 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-lg">
            🐼
          </div>
          <div>
            <p className="text-sm font-bold text-white leading-tight">Stock AI Assistant</p>
            <p className="text-[11px] text-gray-400">Your AI Research Partner</p>
          </div>
        </div>
        <button
          onClick={() => setShowDisclaimer(v => !v)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[#374151] text-sm text-gray-200 hover:border-purple-500/50 hover:text-white transition-all bg-[#111827]"
        >
          <ShieldAlert size={15} />
          Disclaimer
        </button>
      </header>

      {showDisclaimer && (
        <div className="bg-yellow-500/10 border-b border-yellow-500/20 px-5 py-3 text-xs text-yellow-300 flex-shrink-0">
          ⚠ AI-generated responses are for informational purposes only and not financial advice. Always consult a qualified financial advisor before making investment decisions.
          <button onClick={() => setShowDisclaimer(false)} className="ml-3 underline">Dismiss</button>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <Sidebar 
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          onSelectConversation={selectConversation}
          onDeleteConversation={deleteChat}
          onNewChat={newChat} 
        />
        <ChatWindow
          messages={messages}
          loading={loading}
          error={error}
          onSend={sendQuestion}
          onRetry={retryLastQuery}
          onClearError={clearError}
          onCancel={cancelRequest}
        />
      </div>
    </div>
  )
}
