import { useState, useEffect } from 'react'

const STAGES = [
  { label: 'Market research', detail: 'Scanning 6 competitors in Cairo' },
  { label: 'Brand positioning', detail: 'Identifying white spaces' },
  { label: 'Go-to-market strategy', detail: 'Building 90-day playbook' },
  { label: 'Brand naming', detail: 'Checking domain availability' },
  { label: 'Brand identity', detail: 'Writing origin story + voice' },
  { label: 'Visual identity', detail: 'Generating color palette + logos' },
  { label: 'Brand deck', detail: 'Building investor-ready brand deck' },
  { label: 'Live web app', detail: 'Deploying to Lovable' },
]

export default function PipelineDemo() {
  const [completed, setCompleted] = useState<number[]>([])
  const [active, setActive] = useState(0)
  const [done, setDone] = useState(false)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (done) return
    const timer = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(timer)
  }, [done])

  useEffect(() => {
    if (done) return

    const delay = active === 0 ? 1200 : 900 + Math.random() * 800

    const t = setTimeout(() => {
      setCompleted(prev => [...prev, active])
      if (active < STAGES.length - 1) {
        setActive(prev => prev + 1)
      } else {
        setDone(true)
      }
    }, delay)

    return () => clearTimeout(t)
  }, [active, done])

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`
  }

  return (
    <div className="bg-charcoal rounded-2xl p-5 w-full max-w-sm shadow-2xl">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${done ? 'bg-green-400' : 'bg-coral animate-pulse-dot'}`} />
          <span className="text-white/70 text-xs font-body">
            {done ? 'Brand ready' : 'Building Safina...'}
          </span>
        </div>
        <span className="text-white/40 text-xs font-mono">{formatTime(elapsed)}</span>
      </div>

      <div className="space-y-1">
        {STAGES.map((stage, i) => {
          const isCompleted = completed.includes(i)
          const isActive = active === i && !done

          return (
            <div
              key={i}
              className={`flex items-start gap-3 px-3 py-2 rounded-lg transition-all duration-300 ${
                isActive ? 'bg-white/8' : ''
              }`}
              style={{
                opacity: i > active && !isCompleted ? 0.3 : 1,
              }}
            >
              <div className="mt-0.5 flex-shrink-0 w-4 h-4 flex items-center justify-center">
                {isCompleted ? (
                  <svg className="w-4 h-4 text-coral animate-fade-in" fill="none" viewBox="0 0 16 16">
                    <circle cx="8" cy="8" r="7" fill="#FF4D2E" fillOpacity="0.15" />
                    <path d="M5 8l2 2 4-4" stroke="#FF4D2E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : isActive ? (
                  <div className="w-2 h-2 rounded-full bg-coral animate-pulse-dot mt-0.5 ml-1" />
                ) : (
                  <div className="w-1.5 h-1.5 rounded-full bg-white/20 mt-0.5 ml-1" />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <p className={`text-xs font-medium leading-tight ${
                  isCompleted ? 'text-white/80' : isActive ? 'text-white' : 'text-white/30'
                }`}>
                  {stage.label}
                </p>
                {isActive && (
                  <p className="text-xs text-white/40 mt-0.5 animate-slide-in truncate">
                    {stage.detail}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {done && (
        <div className="mt-4 pt-4 border-t border-white/10 animate-fade-in">
          <div className="flex items-center justify-between">
            <span className="text-white/50 text-xs">Brand pack ready</span>
            <button className="bg-coral text-white text-xs px-3 py-1.5 rounded-full font-medium hover:bg-coral-dark transition-colors">
              View results →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}