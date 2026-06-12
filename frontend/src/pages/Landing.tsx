import { useEffect, useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import PipelineDemo from '../components/PipelineDemo'

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
}

const stagger = {
  visible: { transition: { staggerChildren: 0.1 } },
}

function AnimatedSection({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })
  return (
    <motion.div
      ref={ref}
      variants={stagger}
      initial="hidden"
      animate={inView ? 'visible' : 'hidden'}
      className={className}
    >
      {children}
    </motion.div>
  )
}

const OUTPUTS = [
  {
    number: '01',
    title: 'Brand strategy',
    desc: 'Full market research, competitor analysis, positioning map, and a 90-day go-to-market playbook.',
  },
  {
    number: '02',
    title: 'Complete identity',
    desc: 'Brand name, mission, origin story, personality, voice, values, and tagline — all grounded in real data.',
  },
  {
    number: '03',
    title: 'Visual system',
    desc: 'Color palette, typography pair, and three logo concepts — generated as real images.',
  },
  {
    number: '04',
    title: 'Live web app',
    desc: 'A production-ready React application deployed live with a shareable URL. Not a template. Built for your brand.',
  },
]

const PIPELINE = [
  { n: '01', name: 'Market research', desc: 'Live competitor data, reviews, and market gaps sourced from the web in real time', model: 'Groq + Tavily' },
  { n: '02', name: 'Brand positioning', desc: 'Competitive map, white spaces, pain points, and positioning recommendation', model: 'Groq' },
  { n: '03', name: 'Go-to-market strategy', desc: '90-day playbook, channel matrix, copy hooks, and launch roadmap', model: 'Groq' },
  { n: '04', name: 'Brand naming', desc: '15 candidates scored on positioning fit, domain availability, and trademark conflicts', model: 'Groq + Tavily' },
  { n: '05', name: 'Brand identity', desc: 'Mission, origin story, personality, voice, values, and tagline', model: 'Groq' },
  { n: '06', name: 'Visual identity', desc: 'Color palette, typography system, and three logo concepts generated as images', model: 'Gemini' },
  { n: '07', name: 'Brand deck', desc: 'Premium, presentation-ready brand deck with positioning chart and full visual system', model: 'Gemini Pro' },
  { n: '08', name: 'Live web app', desc: 'Full React application deployed live — shareable URL, production-ready', model: 'Lovable' },
]

export default function Landing() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-cream font-body">
      <Navbar />

      {/* ── HERO ── */}
      <section className="pt-40 pb-32 px-6 max-w-6xl mx-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">

          {/* Left */}
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
          >
            <motion.div variants={fadeUp} className="flex items-center gap-2 mb-8">
              <div className="w-1.5 h-1.5 rounded-full bg-coral" />
              <span className="text-xs tracking-widest text-muted uppercase font-medium">
                AI Branding Platform
              </span>
            </motion.div>

            <motion.h1
              variants={fadeUp}
              className="font-display font-extrabold text-6xl lg:text-7xl leading-[1.0] tracking-tighter text-charcoal mb-8 text-balance"
            >
              Your brand,<br />
              <span className="text-coral">built by AI.</span>
            </motion.h1>

            <motion.p
              variants={fadeUp}
              className="text-xl text-muted leading-relaxed max-w-md mb-10"
            >
              From a business idea to a complete brand strategy, visual identity, and live web presence — fully automated, in under ten minutes.
            </motion.p>

            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3">
              <button onClick={() => navigate('/build')} className="bg-coral hover:bg-coral-dark text-white font-medium text-sm px-6 py-3 rounded-full transition-colors duration-200 flex items-center justify-center gap-2">
                Build a brand
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <button onClick={() => navigate('/content')} className="border border-border hover:border-charcoal text-charcoal font-medium text-sm px-6 py-3 rounded-full transition-colors duration-200 flex items-center justify-center gap-2">
                Create content
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </motion.div>
          </motion.div>

          {/* Right — Pipeline Demo */}
          <motion.div
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.7, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="flex justify-center lg:justify-end"
          >
            <PipelineDemo />
          </motion.div>
        </div>
      </section>

      {/* ── DIVIDER ── */}
      <div className="border-t border-border mx-6" />

      {/* ── STATS BAR ── */}
      <AnimatedSection className="max-w-6xl mx-auto px-6 py-16 grid grid-cols-2 md:grid-cols-4 gap-6">
        {[
          { num: '8', label: 'Pipeline stages' },
          { num: '<10m', label: 'Full brand delivery' },
          { num: '15+', label: 'Name candidates' },
          { num: '100%', label: 'AI-generated' },
        ].map((s) => (
          <motion.div key={s.label} variants={fadeUp} className="text-center">
            <div className="font-display font-bold text-4xl text-charcoal tracking-tighter">{s.num}</div>
            <div className="text-sm text-muted mt-2">{s.label}</div>
          </motion.div>
        ))}
      </AnimatedSection>

      {/* ── DIVIDER ── */}
      <div className="border-t border-border mx-6" />

      {/* ── TWO FLOWS ── */}
      <section id="flows" className="max-w-6xl mx-auto px-6 py-32">
        <AnimatedSection>
          <motion.p variants={fadeUp} className="text-xs tracking-widest text-muted uppercase mb-16">
            Two ways in
          </motion.p>
        </AnimatedSection>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border">
          {/* Build a brand */}
          <AnimatedSection className="bg-cream p-14 group">
            <motion.div variants={fadeUp}>
              <span className="font-display font-bold text-7xl text-border select-none">01</span>
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-display font-bold text-4xl text-charcoal mt-6 mb-5 tracking-tight">
              Build a brand
            </motion.h2>
            <motion.p variants={fadeUp} className="text-muted text-base leading-relaxed mb-10 max-w-sm">
              Enter your business idea. BeyondX researches your market, names your brand, builds your identity, and ships a live React app — all in one run.
            </motion.p>
            <motion.ul variants={stagger} className="space-y-3 mb-10">
              {['Market research + competitor analysis', 'Brand naming + domain check', 'Visual identity + logo concepts', 'Premium brand experience document', 'Live hosted web app'].map(item => (
                <motion.li key={item} variants={fadeUp} className="flex items-center gap-2 text-sm text-muted">
                  <div className="w-1 h-1 rounded-full bg-coral flex-shrink-0" />
                  {item}
                </motion.li>
              ))}
            </motion.ul>
            <motion.button
              variants={fadeUp}
              onClick={() => navigate('/build')}
              className="bg-coral hover:bg-coral-dark text-white text-sm font-medium px-6 py-3 rounded-full transition-colors duration-200 flex items-center gap-2"
            >
              Start from scratch
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </motion.button>
          </AnimatedSection>

          {/* Create content */}
          <AnimatedSection className="bg-cream p-14 group">
            <motion.div variants={fadeUp}>
              <span className="font-display font-bold text-7xl text-border select-none">02</span>
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-display font-bold text-4xl text-charcoal mt-6 mb-5 tracking-tight">
              Create content
            </motion.h2>
            <motion.p variants={fadeUp} className="text-muted text-base leading-relaxed mb-10 max-w-sm">
              Already have a brand? Get a full social media strategy, monthly calendar, post captions, and campaign ideas — with an AI chat to follow up.
            </motion.p>
            <motion.ul variants={stagger} className="space-y-3 mb-10">
              {['Trend research for your market', 'Monthly content calendar', 'Post captions + reel scripts', 'Hashtag bank + CTA library', 'Campaign ideas + AI follow-up chat'].map(item => (
                <motion.li key={item} variants={fadeUp} className="flex items-center gap-2 text-sm text-muted">
                  <div className="w-1 h-1 rounded-full bg-charcoal flex-shrink-0" />
                  {item}
                </motion.li>
              ))}
            </motion.ul>
            <motion.button
              variants={fadeUp}
              onClick={() => navigate('/content')}
              className="border border-charcoal hover:bg-charcoal hover:text-cream text-charcoal text-sm font-medium px-6 py-3 rounded-full transition-all duration-200 flex items-center gap-2"
            >
              Start with your brand
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </motion.button>
          </AnimatedSection>
        </div>
      </section>

      {/* ── WHAT YOU GET ── */}
      <section id="outputs" className="bg-charcoal py-32 px-6">
        <div className="max-w-6xl mx-auto">
          <AnimatedSection>
            <motion.p variants={fadeUp} className="text-xs tracking-widest text-white/40 uppercase mb-4">
              What you get
            </motion.p>
            <motion.h2 variants={fadeUp} className="font-display font-bold text-4xl text-white tracking-tight mb-16">
              Everything a brand agency delivers.<br />
              <span className="text-white/40">In minutes, not months.</span>
            </motion.h2>
          </AnimatedSection>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-white/10">
            {OUTPUTS.map((o) => (
              <AnimatedSection key={o.number} className="bg-charcoal p-10">
                <motion.div variants={fadeUp}>
                  <span className="font-display font-bold text-5xl text-white/10 block mb-6">{o.number}</span>
                  <h3 className="font-display font-semibold text-xl text-white mb-4 tracking-tight">{o.title}</h3>
                  <p className="text-sm text-white/50 leading-relaxed">{o.desc}</p>
                </motion.div>
              </AnimatedSection>
            ))}
          </div>
        </div>
      </section>

      {/* ── THE PIPELINE ── */}
      <section id="how-it-works" className="py-32 px-6 max-w-6xl mx-auto">
        <AnimatedSection>
          <motion.p variants={fadeUp} className="text-xs tracking-widest text-muted uppercase mb-4">
            The pipeline
          </motion.p>
          <motion.div variants={fadeUp} className="flex items-baseline justify-between mb-16 border-b border-border pb-8">
            <h2 className="font-display font-bold text-4xl text-charcoal tracking-tight">
              8 stages. Fully automated.
            </h2>
            <span className="text-sm text-muted hidden md:block">Each stage powered by a dedicated AI model</span>
          </motion.div>
        </AnimatedSection>

        <AnimatedSection>
          {PIPELINE.map((stage, i) => (
            <motion.div
              key={stage.n}
              variants={fadeUp}
              className="flex items-start gap-6 py-7 border-b border-border group hover:bg-cream-dark -mx-4 px-4 transition-colors duration-150 rounded-lg cursor-default"
            >
              <span className="text-xs text-muted font-mono pt-0.5 min-w-[28px]">{stage.n}</span>
              <div className="flex-1">
                <h3 className="font-display font-semibold text-base text-charcoal mb-1">{stage.name}</h3>
                <p className="text-sm text-muted">{stage.desc}</p>
              </div>
              <span className="text-xs text-muted border border-border px-3 py-1 rounded-full whitespace-nowrap hidden md:block">
                {stage.model}
              </span>
            </motion.div>
          ))}
        </AnimatedSection>
      </section>

      {/* ── CTA ── */}
      <section className="bg-coral mx-6 mb-24 rounded-2xl px-10 py-24">
        <AnimatedSection className="max-w-2xl mx-auto text-center">
          <motion.h2 variants={fadeUp} className="font-display font-bold text-5xl text-white mb-6 tracking-tight">
            Ready to build your brand?
          </motion.h2>
          <motion.p variants={fadeUp} className="text-white/70 text-lg mb-10 leading-relaxed">
            Enter your business idea and watch BeyondX turn it into a complete brand identity, visual system, and live web presence.
          </motion.p>
          <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3 justify-center">
            <button onClick={() => navigate('/build')} className="bg-white text-coral font-semibold text-sm px-8 py-3 rounded-full hover:bg-cream transition-colors duration-200">
              Build a brand now
            </button>
            <button onClick={() => navigate('/content')} className="border border-white/40 text-white font-medium text-sm px-8 py-3 rounded-full hover:bg-white/10 transition-colors duration-200">
              Create content
            </button>
          </motion.div>
        </AnimatedSection>
      </section>

      {/* ── FOOTER ── */}
      <footer className="border-t border-border px-6 py-10 max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
        <img src="/logo.png" alt="BeyondX" className="h-8 object-contain" />
        <div className="flex flex-col sm:items-end items-center gap-1">
          <span className="text-xs text-muted">AI-powered brand intelligence</span>
          <span className="text-xs text-muted/60">Founded by Hana Haridy &amp; Mohamed Abdelhalim</span>
        </div>
      </footer>
    </div>
  )
}