import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import StageTracker from '../components/StageTracker'
import { useSSE } from '../hooks/useSSE'

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
}

// ── Form ──────────────────────────────────────────────────────────────────────

interface FormData {
  idea: string
  location: string
  differentiator: string
  ideal_customer: string
  non_negotiable: string
}

function BrandForm({ onSubmit }: { onSubmit: (data: FormData) => void }) {
  const [form, setForm] = useState<FormData>({
    idea: '',
    location: '',
    differentiator: '',
    ideal_customer: '',
    non_negotiable: '',
  })
  const navigate = useNavigate()

  const set = (key: keyof FormData) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [key]: e.target.value }))

  const valid = form.idea.trim() && form.location.trim() && form.differentiator.trim()
    && form.ideal_customer.trim() && form.non_negotiable.trim()

  return (
    <div className="min-h-screen bg-cream font-body">
      <Navbar />
      <div className="max-w-2xl mx-auto px-6 pt-36 pb-24">
        <motion.div initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.08 } } }}>

          <motion.button
            variants={fadeUp}
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-sm text-muted hover:text-charcoal transition-colors mb-10"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M10 7H4M6 4L3 7l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Back
          </motion.button>

          <motion.p variants={fadeUp} className="text-xs tracking-widest text-muted uppercase mb-3">
            Build a brand
          </motion.p>
          <motion.h1 variants={fadeUp} className="font-display font-bold text-4xl text-charcoal tracking-tight mb-2">
            Tell us about your idea.
          </motion.h1>
          <motion.p variants={fadeUp} className="text-muted text-base mb-12 leading-relaxed">
            Five questions. BeyondX does the rest.
          </motion.p>

          <div className="space-y-8">
            <motion.div variants={fadeUp}>
              <label className="block text-sm font-medium text-charcoal mb-2">
                What's your business idea?
              </label>
              <textarea
                value={form.idea}
                onChange={set('idea')}
                rows={3}
                placeholder="e.g. An online bookstore specialising in Arabic fiction for university students in Cairo"
                className="w-full px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors resize-none"
              />
            </motion.div>

            <motion.div variants={fadeUp}>
              <label className="block text-sm font-medium text-charcoal mb-2">
                Where is your business located?
              </label>
              <input
                type="text"
                value={form.location}
                onChange={set('location')}
                placeholder="e.g. Cairo, Egypt"
                className="w-full px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors"
              />
            </motion.div>

            <motion.div variants={fadeUp}>
              <label className="block text-sm font-medium text-charcoal mb-2">
                What makes your concept different?
              </label>
              <p className="text-xs text-muted mb-2">Don't say "quality" or "service" — be specific</p>
              <input
                type="text"
                value={form.differentiator}
                onChange={set('differentiator')}
                placeholder="e.g. Arabic-only catalogue with same-day delivery"
                className="w-full px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors"
              />
            </motion.div>

            <motion.div variants={fadeUp}>
              <label className="block text-sm font-medium text-charcoal mb-2">
                Describe your ideal customer in one sentence.
              </label>
              <input
                type="text"
                value={form.ideal_customer}
                onChange={set('ideal_customer')}
                placeholder="e.g. A 22-year-old Cairo university student who reads Arabic fiction"
                className="w-full px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors"
              />
            </motion.div>

            <motion.div variants={fadeUp}>
              <label className="block text-sm font-medium text-charcoal mb-2">
                What is the one thing you refuse to compromise on?
              </label>
              <input
                type="text"
                value={form.non_negotiable}
                onChange={set('non_negotiable')}
                placeholder="e.g. Never out of stock on bestsellers"
                className="w-full px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors"
              />
            </motion.div>

            <motion.div variants={fadeUp} className="pt-2">
              <button
                onClick={() => valid && onSubmit(form)}
                disabled={!valid}
                className={`w-full py-4 rounded-xl font-medium text-sm transition-all duration-200 flex items-center justify-center gap-2 ${
                  valid
                    ? 'bg-coral hover:bg-coral-dark text-white'
                    : 'bg-border text-muted cursor-not-allowed'
                }`}
              >
                Build my brand
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}

// ── Progress ──────────────────────────────────────────────────────────────────

function BrandProgress({
  stages,
  brandName,
}: {
  stages: ReturnType<typeof useSSE>['state']['stages']
  brandName?: string
}) {
  const done = stages.filter(s => s.status === 'done' || s.status === 'warning').length
  const total = stages.length
  const pct = Math.round((done / total) * 100)

  return (
    <div className="min-h-screen bg-cream font-body">
      <Navbar />
      <div className="max-w-xl mx-auto px-6 pt-36 pb-24">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>

          <div className="flex items-center justify-between mb-2">
            <p className="text-xs tracking-widest text-muted uppercase">Pipeline running</p>
            <span className="text-sm font-medium text-charcoal">{pct}%</span>
          </div>

          {/* Progress bar */}
          <div className="h-1 bg-border rounded-full mb-10 overflow-hidden">
            <motion.div
              className="h-full bg-coral rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            />
          </div>

          <StageTracker stages={stages} type="brand" brandName={brandName} />

          <p className="text-xs text-muted text-center mt-8">
            This takes 5–10 minutes. Please keep this tab open.
          </p>
        </motion.div>
      </div>
    </div>
  )
}

// ── Results ───────────────────────────────────────────────────────────────────

function BrandResults({ result }: { result: Record<string, unknown> }) {
  const navigate = useNavigate()
  const colors = result.colors as Array<{ name: string; hex: string; role: string; rationale: string }>
  const topNames = result.top_names as Array<{ name: string; score: number; domain_com: string }>
  const pains = result.pain_points as Array<{ theme: string; description: string }>
  const whiteSpaces = result.white_spaces as string[]
  const logoPaths = result.logo_paths as string[] | undefined
  const brandSafe = (result.brand_name as string)?.toLowerCase().replace(/\s+/g, '_')

  return (
    <div className="min-h-screen bg-cream font-body">
      <Navbar />
      <div className="max-w-4xl mx-auto px-6 pt-36 pb-24">
        <motion.div initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.08 } } }}>

          {/* Header */}
          <motion.div variants={fadeUp} className="mb-16">
            <p className="text-xs tracking-widest text-muted uppercase mb-3">Brand ready</p>
            <h1 className="font-display font-bold text-6xl text-charcoal tracking-tighter mb-3">
              {result.brand_name as string}
            </h1>
            <p className="text-xl text-muted italic">"{result.tagline as string}"</p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

            {/* Mission */}
            <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7 md:col-span-2">
              <p className="text-xs tracking-widest text-muted uppercase mb-3">Mission</p>
              <p className="text-base text-charcoal leading-relaxed">{result.mission as string}</p>
            </motion.div>

            {/* Colors */}
            {colors?.length > 0 && (
              <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7">
                <p className="text-xs tracking-widest text-muted uppercase mb-5">Color palette</p>
                <div className="space-y-4">
                  {colors.map(c => (
                    <div key={c.hex} className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-xl flex-shrink-0 shadow-sm" style={{ background: c.hex }} />
                      <div>
                        <p className="text-sm font-medium text-charcoal">{c.name}</p>
                        <p className="text-xs text-muted uppercase tracking-wider">{c.hex} · {c.role}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Logos */}
            {logoPaths && logoPaths.length > 0 && (
              <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7 md:col-span-2">
                <p className="text-xs tracking-widest text-muted uppercase mb-5">Logo concepts</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {logoPaths.map((path, i) => {
                    const filename = path.split('/').pop()
                    const url = `http://localhost:8000/brand-packs/${brandSafe}/${filename}`
                    return (
                      <div key={path} className="border border-border rounded-xl p-6 flex flex-col items-center gap-3 bg-cream-dark">
                        <img
                          src={url}
                          alt={`Logo concept ${i + 1}`}
                          className="max-h-48 w-full object-contain"
                        />
                        <p className="text-xs text-muted uppercase tracking-wider">Concept {i + 1}</p>
                      </div>
                    )
                  })}
                </div>
              </motion.div>
            )}

            {/* Top names */}
            {topNames?.length > 0 && (
              <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7">
                <p className="text-xs tracking-widest text-muted uppercase mb-5">Name candidates</p>
                <div className="space-y-3">
                  {topNames.slice(0, 5).map((n, i) => (
                    <div key={n.name} className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted font-mono w-4">{i + 1}</span>
                        <span className={`text-sm font-medium ${i === 0 ? 'text-coral' : 'text-charcoal'}`}>
                          {n.name}
                          {i === 0 && <span className="ml-2 text-xs bg-coral/10 text-coral px-2 py-0.5 rounded-full">Selected</span>}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span className={n.domain_com === 'available' ? 'text-green-600' : 'text-red-400'}>
                          .com {n.domain_com === 'available' ? '✓' : '✗'}
                        </span>
                        <span className="text-muted/50">·</span>
                        <span>{n.score?.toFixed(1)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Positioning */}
            <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7 md:col-span-2">
              <p className="text-xs tracking-widest text-muted uppercase mb-3">Positioning statement</p>
              <p className="text-base text-charcoal leading-relaxed italic">"{result.positioning as string}"</p>
            </motion.div>

            {/* White spaces */}
            {whiteSpaces?.length > 0 && (
              <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7">
                <p className="text-xs tracking-widest text-muted uppercase mb-4">Market white spaces</p>
                <div className="space-y-3">
                  {whiteSpaces.map((ws, i) => (
                    <div key={i} className="flex gap-3">
                      <div className="w-1 rounded-full bg-coral flex-shrink-0 mt-1" />
                      <p className="text-sm text-charcoal leading-relaxed">{ws}</p>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Pain points */}
            {pains?.length > 0 && (
              <motion.div variants={fadeUp} className="bg-white border border-border rounded-2xl p-7">
                <p className="text-xs tracking-widest text-muted uppercase mb-4">Customer pain points</p>
                <div className="space-y-3">
                  {pains.map((p, i) => (
                    <div key={i}>
                      <p className="text-sm font-medium text-charcoal">{p.theme}</p>
                      <p className="text-xs text-muted mt-0.5">{p.description}</p>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Origin story */}
            {result.origin_story && (
              <motion.div variants={fadeUp} className="bg-charcoal rounded-2xl p-7 md:col-span-2">
                <p className="text-xs tracking-widest text-white/40 uppercase mb-4">Origin story</p>
                <p className="text-base text-white/80 leading-relaxed">{result.origin_story as string}</p>
              </motion.div>
            )}

            {/* Actions */}
            <motion.div variants={fadeUp} className="md:col-span-2 flex flex-wrap gap-3 pt-4">
              {result.lovable_url && (
                <a
                  href={result.lovable_url as string}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="bg-coral hover:bg-coral-dark text-white text-sm font-medium px-6 py-3 rounded-full transition-colors flex items-center gap-2"
                >
                  Open live web app
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </a>
              )}
              {result.brand_book_path && (
                <a
                  href={`http://localhost:8000${result.brand_book_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="border border-border hover:border-charcoal text-charcoal text-sm font-medium px-6 py-3 rounded-full transition-colors"
                >
                  View brand deck
                </a>
              )}
              <button
                onClick={() => navigate('/')}
                className="border border-border hover:border-charcoal text-charcoal text-sm font-medium px-6 py-3 rounded-full transition-colors"
              >
                Build another brand
              </button>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BrandPipeline() {
  const { state, run, reset } = useSSE(8)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (data: FormData) => {
    setSubmitted(true)
    run('http://localhost:8000/api/brand/run', data)
  }

  const brandName = state.result?.brand_name as string | undefined
    ?? state.stages.find(s => s.status === 'done' && s.stage === 5)
      ? undefined : undefined

  return (
    <AnimatePresence mode="wait">
      {!submitted && (
        <motion.div key="form" exit={{ opacity: 0 }}>
          <BrandForm onSubmit={handleSubmit} />
        </motion.div>
      )}

      {submitted && state.status !== 'complete' && state.status !== 'error' && (
        <motion.div key="progress" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <BrandProgress stages={state.stages} brandName={brandName} />
        </motion.div>
      )}

      {state.status === 'complete' && state.result && (
        <motion.div key="results" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <BrandResults result={state.result} />
        </motion.div>
      )}

      {state.status === 'error' && (
        <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="min-h-screen bg-cream flex items-center justify-center font-body"
        >
          <div className="text-center max-w-md px-6">
            <p className="text-xs tracking-widest text-muted uppercase mb-4">Something went wrong</p>
            <p className="text-sm text-muted mb-6">{state.error}</p>
            <button onClick={reset} className="bg-coral text-white text-sm font-medium px-6 py-3 rounded-full">
              Try again
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}