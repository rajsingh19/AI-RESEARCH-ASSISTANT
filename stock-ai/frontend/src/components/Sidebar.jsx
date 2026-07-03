import { Plus, MessageSquare, Sparkles, ChevronDown } from 'lucide-react'

const MOCK_RECENT = [
  { id: 1, text: "Summarise TCS's latest results", time: "2 mins ago" },
  { id: 2, text: "Compare HDFC vs ICICI margins", time: "1 hour ago" },
  { id: 3, text: "Why did Reliance stock fall today?", time: "3 hours ago" },
  { id: 4, text: "Top growth drivers for Infosys", time: "Yesterday" },
  { id: 5, text: "What are the key risks for TCS?", time: "2 days ago" },
]

export default function Sidebar({ messages, onNewChat }) {
  const userMessages = messages.filter(m => m.role === 'user')
  const recentChats = userMessages.length > 0
    ? userMessages.slice(-5).reverse().map((m, i) => ({ id: m.id, text: m.content, time: i === 0 ? 'Just now' : `${i * 2} mins ago` }))
    : MOCK_RECENT

  return (
    <aside className="w-72 flex-shrink-0 flex flex-col bg-[#0d1526] border-r border-[#1F2937] h-full">
      {/* New Chat */}
      <div className="p-4">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-colors shadow-lg"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Recent Chats */}
      <div className="flex-1 overflow-y-auto px-3">
        <p className="text-xs text-gray-500 font-medium px-2 mb-2">Recent Chats</p>
        <div className="space-y-1">
          {recentChats.map((chat, i) => (
            <div
              key={chat.id}
              className={`px-3 py-3 rounded-xl cursor-pointer transition-colors group ${i === 0 ? 'bg-[#1a2235] border border-[#2d3748]' : 'hover:bg-[#111827]'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-gray-200 leading-snug truncate flex-1">{chat.text}</p>
                {i === 0 && <MessageSquare size={14} className="text-gray-500 flex-shrink-0 mt-0.5" />}
              </div>
              <p className="text-xs text-gray-500 mt-1">{chat.time}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Info Card */}
      <div className="mx-3 mb-3 p-4 rounded-xl bg-[#111827] border border-[#1F2937] text-center">
        <div className="flex justify-center mb-2">
          <Sparkles size={22} className="text-indigo-400" />
        </div>
        <p className="text-sm text-gray-200 font-medium leading-snug mb-1">
          Ask anything about stocks,<br />results, news, filings and more.
        </p>
        <p className="text-xs text-gray-500">Our AI assistant is powered by<br />advanced LLM & real-time data.</p>
      </div>

      {/* Profile */}
      <div className="px-3 pb-4">
        <div className="flex items-center gap-3 px-3 py-3 rounded-xl bg-[#111827] border border-[#1F2937]">
          <div className="w-9 h-9 rounded-full bg-indigo-600 flex items-center justify-center text-sm font-bold text-white flex-shrink-0">
            RS
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white truncate">Raj Singh</p>
            <p className="text-xs text-gray-500 truncate">rajsingh190904@gmail.com</p>
          </div>
          <ChevronDown size={15} className="text-gray-500 flex-shrink-0" />
        </div>
      </div>
    </aside>
  )
}
