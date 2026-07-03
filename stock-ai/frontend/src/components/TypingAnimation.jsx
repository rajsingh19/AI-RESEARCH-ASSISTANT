import { motion } from 'framer-motion'

const dot = {
  animate: { y: [0, -6, 0] },
  transition: { duration: 0.6, repeat: Infinity, ease: 'easeInOut' },
}

export default function TypingAnimation() {
  return (
    <div className="flex items-center gap-1 px-1 py-1">
      {[0, 0.15, 0.3].map((delay, i) => (
        <motion.span
          key={i}
          className="w-2 h-2 rounded-full bg-purple-400"
          animate={dot.animate}
          transition={{ ...dot.transition, delay }}
        />
      ))}
    </div>
  )
}
