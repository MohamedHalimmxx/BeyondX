import { motion } from 'framer-motion'
import type { Stage } from '../hooks/useSSE'

const BRAND_STAGE_NAMES = [
  'Market research',
  'Brand positioning',
  'Go-to-market strategy',
  'Brand naming',
  'Brand identity',
  'Visual identity',
  'Brand deck',
  'Live web app',
]

const CONTENT_STAGE_NAMES = [
  'Brand context',
  'Trend research',
  'Content strategy',
  'Content calendar',
  'Post generation',
  'Campaigns',
]

interface StageTrackerProps {
  stages: Stage[]
  type: 'brand' | 'content'
  brandName?: string
}

export default function StageTracker({ stages, type, brandName }: StageTrackerProps) {
  const defaultNames = type === 'brand' ? BRAND_STAGE_NAMES : CONTENT_STAGE_NAMES

  return (
    <div className="space-y-1">
      {stages.map((stage, i) => {
        const name = stage.name || defaultNames[i] || `Stage ${stage.stage}`
        const isDone = stage.status === 'done'
        const isRunning = stage.status === 'running'
        const isWarning = stage.status === 'warning'
        const isPending = stage.status === 'pending'

        return (
          <motion.div
            key={stage.stage}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: isPending ? 0.35 : 1, x: 0 }}
            transition={{ duration: 0.3, delay: i * 0.04 }}
            className={`flex items-center gap-4 px-4 py-3 rounded-xl transition-all duration-300 ${
              isRunning ? 'bg-cream-dark' : ''
            }`}
          >
            {/* Icon */}
            <div className="w-6 h-6 flex-shrink-0 flex items-center justify-center">
              {isDone && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                >
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                    <circle cx="10" cy="10" r="9" fill="#FF4D2E" fillOpacity="0.12" />
                    <path d="M6.5 10l2.5 2.5 4.5-5" stroke="#FF4D2E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </motion.div>
              )}
              {isRunning && (
                <div className="w-2 h-2 rounded-full bg-coral animate-pulse" />
              )}
              {isWarning && (
                <div className="w-2 h-2 rounded-full bg-amber-400" />
              )}
              {isPending && (
                <div className="w-1.5 h-1.5 rounded-full bg-border" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <span className={`text-sm font-medium ${
                  isDone ? 'text-charcoal' :
                  isRunning ? 'text-charcoal' :
                  isWarning ? 'text-amber-600' :
                  'text-muted'
                }`}>
                  {name}
                </span>
                {isDone && stage.duration_ms && (
                  <span className="text-xs text-muted flex-shrink-0">
                    {(stage.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              {isRunning && stage.detail && (
                <motion.p
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="text-xs text-muted mt-0.5 truncate"
                >
                  {stage.detail}
                </motion.p>
              )}
            </div>

            {/* Stage number */}
            <span className="text-xs text-muted/50 font-mono flex-shrink-0">
              {String(stage.stage).padStart(2, '0')}
            </span>
          </motion.div>
        )
      })}

      {brandName && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 px-4 py-3 rounded-xl bg-coral/5 border border-coral/20"
        >
          <p className="text-xs text-muted">Building</p>
          <p className="text-lg font-display font-bold text-charcoal tracking-tight">{brandName}</p>
        </motion.div>
      )}
    </div>
  )
}