import { Plus, MessageSquare, Sparkles, ChevronDown, Trash2 } from 'lucide-react'

export default function Sidebar({
  conversations = [],
  selectedConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewChat
}) {
  // Chronological grouping helper
  const getGroupedConversations = () => {
    const groups = {
      today: [],
      yesterday: [],
      last7Days: [],
      last30Days: [],
      older: []
    }

    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const yesterdayStart = todayStart - 24 * 60 * 60 * 1000
    const sevenDaysAgoStart = todayStart - 6 * 24 * 60 * 60 * 1000
    const thirtyDaysAgoStart = todayStart - 29 * 24 * 60 * 60 * 1000

    conversations.forEach(conv => {
      const updatedTime = new Date(conv.updatedAt).getTime()
      if (updatedTime >= todayStart) {
        groups.today.push(conv)
      } else if (updatedTime >= yesterdayStart) {
        groups.yesterday.push(conv)
      } else if (updatedTime >= sevenDaysAgoStart) {
        groups.last7Days.push(conv)
      } else if (updatedTime >= thirtyDaysAgoStart) {
        groups.last30Days.push(conv)
      } else {
        groups.older.push(conv)
      }
    })

    return groups
  }

  const grouped = getGroupedConversations()

  const renderGroup = (title, items) => {
    if (items.length === 0) return null
    return (
      <div className="mb-4">
        <p className="text-[11px] text-gray-500 font-bold tracking-wider uppercase px-2 mb-2">{title}</p>
        <div className="space-y-1">
          {items.map(conv => {
            const isActive = conv.id === selectedConversationId
            return (
              <div
                key={conv.id}
                onClick={() => onSelectConversation(conv.id)}
                className={`px-3 py-2.5 rounded-xl cursor-pointer transition-all flex items-center justify-between group ${
                  isActive
                    ? 'bg-[#1a2235] border border-[#2d3748]/80 text-white'
                    : 'text-gray-300 hover:bg-[#111827] hover:text-white'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <MessageSquare size={14} className={isActive ? 'text-indigo-400' : 'text-gray-500'} />
                  <span className="text-sm font-medium truncate leading-tight flex-1 pr-1">{conv.title}</span>
                </div>
                {onDeleteConversation && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteConversation(conv.id)
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#1F2937] rounded-lg text-gray-500 hover:text-red-400 transition-all ml-1.5 flex-shrink-0"
                    title="Delete Chat"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

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

      {/* Grouped Conversations Scroll area */}
      <div className="flex-1 overflow-y-auto px-3 select-none">
        {conversations.length === 0 ? (
          <div className="text-center py-8 text-xs text-gray-500">No conversations yet</div>
        ) : (
          <>
            {renderGroup("Today", grouped.today)}
            {renderGroup("Yesterday", grouped.yesterday)}
            {renderGroup("Previous 7 Days", grouped.last7Days)}
            {renderGroup("Previous 30 Days", grouped.last30Days)}
            {renderGroup("Older", grouped.older)}
          </>
        )}
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
