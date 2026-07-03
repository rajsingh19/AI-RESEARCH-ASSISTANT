import { motion } from 'framer-motion'
import { TrendingUp, Newspaper, BarChart2, Scale, AlertTriangle, DollarSign, Activity, Search } from 'lucide-react'

const CHIPS = [
  { label: 'Latest TCS news', icon: Newspaper },
  { label: 'Compare TCS and Infosys revenue', icon: Scale },
  { label: 'What is Reliance profit?', icon: TrendingUp },
  { label: 'Which company has highest EPS?', icon: BarChart2 },
  { label: 'What does Infosys do?', icon: Search },
  { label: 'Key risks for TCS', icon: AlertTriangle },
  { label: 'TCS PE ratio', icon: DollarSign },
  { label: 'Infosys growth strategy', icon: Activity },
]

export default function SuggestionChips({ onSelect }) {
  return (
    <div className="px-4 pb-4">
      <p className="text-xs text-gray-500 mb-3 text-center">Try asking</p>
      <div className="flex flex-wrap gap-2 justify-center">
        {CHIPS.map((chip, i) => {
          const Icon = chip.icon
          return (
            <motion.button
              key={chip.label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => onSelect(chip.label)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-[#111827] border border-[#1F2937] text-gray-300 hover:border-purple-500/50 hover:text-purple-300 hover:bg-purple-500/5 transition-all"
            >
              <Icon size={12} />
              {chip.label}
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
