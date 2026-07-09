import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ExternalLink } from 'lucide-react'

// Source favicon helpers
const SOURCE_ICONS = {
  'investor.tcs.com': '📈',
  'economictimes.com': '📰',
  'moneycontrol.com': '📊',
  'business-standard.com': '📋',
}

function getFavicon(url) {
  try {
    const host = new URL(url).hostname.replace('www.', '')
    return `https://www.google.com/s2/favicons?domain=${host}&sz=32`
  } catch {
    return null
  }
}

function getSourceLabel(url) {
  try {
    return new URL(url).hostname.replace('www.', '')
  } catch {
    return url
  }
}

// Bouncing three-dot thinking indicator
function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 bg-transparent px-3 py-2.5 select-none mt-1">
      <span 
        className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" 
        style={{ animationDelay: '0ms' }} 
      />
      <span 
        className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" 
        style={{ animationDelay: '150ms' }} 
      />
      <span 
        className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" 
        style={{ animationDelay: '300ms' }} 
      />
    </div>
  )
}

// Metric card — matches the 4-column grid in the image
function MetricCard({ label, value, change, positive }) {
  return (
    <div className="flex-1 min-w-0 px-5 py-4 border-r border-[#2d3748] last:border-r-0">
      <p className="text-sm text-gray-400 mb-1">{label}</p>
      <p className="text-xl font-bold text-white mb-1">{value}</p>
      {change && (
        <p className={`text-xs font-medium flex items-center gap-0.5 ${positive !== false ? 'text-green-400' : 'text-red-400'}`}>
          {positive !== false ? '▲' : '▼'} {change}
        </p>
      )}
    </div>
  )
}

// Parse financial_data into metric cards
function FinancialMetrics({ data }) {
  if (!data || Object.keys(data).length === 0) return null

  const entries = Object.entries(data)
  const metrics = []

  entries.forEach(([ticker, d]) => {
    const period = d.reporting_period ? ` (${d.reporting_period})` : ''
    if (d.revenue) metrics.push({ label: `Revenue${period}`, value: `₹${Number(d.revenue).toLocaleString('en-IN')} Cr`, change: d.revenue_yoy ? `${d.revenue_yoy}% YoY` : null })
    if (d.profit) metrics.push({ label: `Net Profit${period}`, value: `₹${Number(d.profit).toLocaleString('en-IN')} Cr`, change: d.profit_yoy ? `${d.profit_yoy}% YoY` : null })
    if (d.operating_margin) metrics.push({ label: `Operating Margin${period}`, value: `${d.operating_margin}%`, change: d.margin_yoy ? `${d.margin_yoy}% YoY` : null })
    if (d.eps) metrics.push({ label: `EPS${period}`, value: `₹${d.eps}`, change: d.eps_yoy ? `${d.eps_yoy}% YoY` : null })
  })

  if (metrics.length === 0) return null

  return (
    <div className="mt-3 rounded-xl border border-[#2d3748] overflow-hidden">
      <div className="flex divide-x divide-[#2d3748]">
        {metrics.slice(0, 4).map((m, i) => (
          <MetricCard key={i} {...m} />
        ))}
      </div>
    </div>
  )
}

// Source card row — matches the image exactly
function SourceRow({ sources, documents, news }) {
  const items = []

  // Add document sources
  if (documents?.length) {
    documents.forEach((doc, i) => {
      items.push({ title: doc.source || `Document ${i + 1}`, domain: doc.source, url: doc.url })
    })
  }

  // Add news sources
  if (news?.length) {
    const unique = news.filter((n, i, arr) => arr.findIndex(x => x.article_id === n.article_id) === i)
    unique.slice(0, 3).forEach(n => {
      items.push({ title: n.source || n.title?.slice(0, 30), domain: n.url, url: n.url })
    })
  }

  // Add plain sources
  if (sources?.length) {
    sources.forEach((s, i) => {
      if (typeof s === 'string' && s.startsWith('http')) {
        items.push({ title: getSourceLabel(s), domain: s, url: s })
      } else if (typeof s === 'string') {
        items.push({ title: s, domain: null, url: null })
      }
    })
  }

  if (items.length === 0) return null

  return (
    <div className="mt-4">
      <p className="text-sm font-semibold text-gray-200 mb-3">Sources</p>
      <div className="flex flex-wrap gap-3">
        {items.slice(0, 4).map((item, i) => {
          const favicon = item.url ? getFavicon(item.url) : null
          const domain = item.url ? getSourceLabel(item.url) : item.title
          return (
            <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#1a2235] border border-[#2d3748] min-w-[140px]">
              {favicon ? (
                <img src={favicon} alt="" className="w-6 h-6 rounded-md flex-shrink-0" onError={e => e.target.style.display = 'none'} />
              ) : (
                <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center text-xs flex-shrink-0">📄</div>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-gray-200 truncate">{item.title}</p>
                <p className="text-[11px] text-gray-500 truncate">{domain}</p>
              </div>
              {item.url && (
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink size={12} className="text-gray-500 hover:text-gray-300 flex-shrink-0" />
                </a>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

export default function Message({ message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[60%]">
          <div className="bg-indigo-600 text-white px-5 py-3 rounded-2xl rounded-br-sm text-sm leading-relaxed shadow-lg">
            {message.content}
          </div>
          <p className="text-[11px] text-gray-500 text-right mt-1 pr-1">{formatTime(message.id)}</p>
        </div>
      </div>
    )
  }

  const isThinking = message.loading && (!message.content || message.content.trim() === '')

  return (
    <div className="flex items-start gap-3">
      {/* Avatar */}
      <div className="w-9 h-9 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-base flex-shrink-0 mt-1">
        📈
      </div>

      {isThinking ? (
        /* Thinking animation when no token has arrived yet */
        <ThinkingIndicator />
      ) : (
        /* Card Container - grows naturally */
        <div className="flex-1 min-w-0 bg-[#111827] border border-[#1F2937] rounded-2xl rounded-tl-sm px-5 py-4 shadow-lg">
          {message.loading ? (
            /* Stream fast text display to avoid flickering and layout shifts */
            <div className="whitespace-pre-wrap leading-relaxed text-gray-200 text-sm">
              {message.content}
              <span className="ml-1 text-indigo-400 font-semibold animate-pulse align-middle">▌</span>
            </div>
          ) : (
            /* Final rich Markdown rendering once stream is complete */
            <div className="prose-dark text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          )}

          {/* Financial metrics grid */}
          <FinancialMetrics data={message.financial_data} />

          {/* Sources row */}
          <SourceRow sources={message.sources} documents={message.documents} news={message.news} />

          {/* Warnings */}
          {message.warnings?.length > 0 && (
            <div className="mt-3 text-xs text-yellow-400/80 bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-3 py-2">
              ⚠ {message.warnings.join(', ')} not found in database.
            </div>
          )}

          {/* Timestamp */}
          <p className="text-[11px] text-gray-500 mt-3">{formatTime(message.id)}</p>
        </div>
      )}
    </div>
  )
}
