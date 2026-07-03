import { ExternalLink, FileText, Newspaper, Database } from 'lucide-react'
import { motion } from 'framer-motion'

const getIcon = (source) => {
  const s = source.toLowerCase()
  if (s === 'sqlite') return <Database size={13} className="text-blue-400" />
  if (s.endsWith('.pdf') || s.includes('report') || s.includes('doc'))
    return <FileText size={13} className="text-purple-400" />
  return <Newspaper size={13} className="text-green-400" />
}

const getColor = (source) => {
  const s = source.toLowerCase()
  if (s === 'sqlite') return 'border-blue-500/20 bg-blue-500/5'
  if (s.endsWith('.pdf') || s.includes('report')) return 'border-purple-500/20 bg-purple-500/5'
  return 'border-green-500/20 bg-green-500/5'
}

export default function SourceCard({ source, url, publishedAt, index }) {
  const label = source.length > 45 ? source.slice(0, 45) + '…' : source

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.05 }}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${getColor(source)} cursor-default`}
    >
      {getIcon(source)}
      <span className="text-gray-300 flex-1 min-w-0 truncate">{label}</span>
      {publishedAt && (
        <span className="text-gray-500 flex-shrink-0">
          {new Date(publishedAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
        </span>
      )}
      {url && (
        <a href={url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
          <ExternalLink size={11} className="text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0" />
        </a>
      )}
    </motion.div>
  )
}
