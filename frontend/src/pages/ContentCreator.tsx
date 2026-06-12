import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import { useSSE } from '../hooks/useSSE'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  isProgress?: boolean
  isSuggestion?: boolean
  isResults?: boolean
  result?: Record<string, unknown>
}

interface Session {
  id: string
  brandName: string
  createdAt: Date
  messages: Message[]
  result: Record<string, unknown> | null
  config: Record<string, unknown> | null
  phase: 'intake' | 'running' | 'chat'
  extractedFields: Record<string, unknown>
}

const genId = () => Math.random().toString(36).slice(2)

const SUGGESTIONS = [
  "Give me next month's content strategy",
  "Generate 5 more posts for Instagram",
  "Create a Ramadan campaign",
  "What topics haven't we covered yet?",
  "Write 3 captions in a more casual tone",
  "Give me 15 new hashtags",
]

const WELCOME = `Hi! I'm your AI Content Strategist. 👋

Tell me about your brand and I'll build a complete content strategy — posts, campaigns, hashtags, and more.

You can describe your brand naturally, like:
*"I have a coffee shop called Bloom in Cairo, we're on Instagram and TikTok, posting about 12 times a month, founded in 2023"*

Or just start with your brand name and I'll ask for the rest.`

const STAGE_NAMES: Record<number, string> = {
  1: 'Researching your brand and market...',
  2: 'Analyzing trends for your platforms...',
  3: 'Building your content strategy...',
  4: 'Planning your monthly calendar...',
  5: 'Writing posts and captions...',
  6: 'Generating campaign ideas...',
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  if (msg.isProgress) {
    return (
      <div className="flex justify-start mb-3">
        <div className="flex items-center gap-2 text-xs text-muted bg-cream-dark px-3 py-2 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-coral animate-pulse" />
          {msg.content}
        </div>
      </div>
    )
  }
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex mb-4 ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-coral flex-shrink-0 flex items-center justify-center mr-2 mt-0.5">
          <span className="text-white text-xs font-bold font-display">X</span>
        </div>
      )}
      <div
        className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-charcoal text-white rounded-tr-sm'
            : 'bg-white border border-border text-charcoal rounded-tl-sm'
        }`}
        dangerouslySetInnerHTML={{
          __html: msg.content
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
        }}
      />
    </motion.div>
  )
}

function ResultsSummary({ result }: { result: Record<string, unknown> }) {
  const posts = result.generated_posts as Array<{ platform: string; content_type: string; topic: string; caption: string; hashtags: string[] }> || []
  const campaigns = result.campaign_ideas as Array<{ name: string; duration_days: number; objective: string }> || []
  const pillars = result.content_pillars as Array<{ name: string; percentage: number }> || []
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="bg-white border border-border rounded-2xl overflow-hidden mb-4">
      <div className="bg-charcoal px-4 py-3 flex items-center justify-between">
        <span className="text-white text-sm font-medium font-display">Content pack ready</span>
        <span className="text-white/50 text-xs">{posts.length} posts · {campaigns.length} campaigns</span>
      </div>
      {pillars.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <p className="text-xs text-muted uppercase tracking-wider mb-2">Content pillars</p>
          <div className="space-y-2">
            {pillars.map(p => (
              <div key={p.name}>
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="text-charcoal font-medium">{p.name}</span>
                  <span className="text-coral">{p.percentage}%</span>
                </div>
                <div className="h-1 bg-border rounded-full overflow-hidden">
                  <div className="h-full bg-coral rounded-full" style={{ width: `${p.percentage}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {posts.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => setExpanded(expanded === 'posts' ? null : 'posts')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Posts ({posts.length})</p>
            <span className="text-xs text-muted">{expanded === 'posts' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'posts' && (
            <div className="mt-3 space-y-3 max-h-64 overflow-y-auto">
              {posts.map((p, i) => (
                <div key={i} className="border border-border rounded-lg p-3">
                  <div className="flex gap-2 mb-1 flex-wrap">
                    <span className="text-xs bg-cream-dark text-muted px-2 py-0.5 rounded">{p.platform}</span>
                    <span className="text-xs bg-cream-dark text-muted px-2 py-0.5 rounded">{p.content_type}</span>
                  </div>
                  <p className="text-xs font-medium text-charcoal mb-1">{p.topic}</p>
                  <p className="text-xs text-muted line-clamp-2">{p.caption}</p>
                  {p.hashtags?.length > 0 && <p className="text-xs text-coral mt-1">{p.hashtags.slice(0, 4).join(' ')}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {campaigns.length > 0 && (
        <div className="px-4 py-3">
          <button onClick={() => setExpanded(expanded === 'campaigns' ? null : 'campaigns')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Campaigns ({campaigns.length})</p>
            <span className="text-xs text-muted">{expanded === 'campaigns' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'campaigns' && (
            <div className="mt-3 space-y-2">
              {campaigns.map((c, i) => (
                <div key={i} className="border border-border rounded-lg p-3">
                  <p className="text-xs font-medium text-charcoal">{c.name}</p>
                  <p className="text-xs text-muted">{c.duration_days} days · {String(c.objective).slice(0, 80)}...</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Sidebar({ sessions, activeId, onSelect, onNew }: {
  sessions: Session[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}) {
  return (
    <div className="w-60 flex-shrink-0 border-r border-border bg-cream-dark flex flex-col">
      <div className="p-3 border-b border-border">
        <button onClick={onNew} className="w-full bg-coral hover:bg-coral-dark text-white text-sm font-medium py-2 rounded-xl transition-colors flex items-center justify-center gap-2">
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          New session
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {sessions.length === 0 && <p className="text-xs text-muted text-center mt-8 px-4">No sessions yet.</p>}
        {sessions.map(s => (
          <button key={s.id} onClick={() => onSelect(s.id)} className={`w-full text-left px-3 py-2.5 rounded-xl mb-1 transition-colors ${s.id === activeId ? 'bg-white border border-border' : 'hover:bg-white/60'}`}>
            <p className="text-sm font-medium text-charcoal truncate">{s.brandName || 'New session'}</p>
            <p className="text-xs text-muted mt-0.5">{s.phase === 'intake' ? 'Setting up...' : s.phase === 'running' ? 'Running...' : `${(s.result?.generated_posts as unknown[])?.length || 0} posts`}</p>
            <p className="text-xs text-muted/50 mt-0.5">{s.createdAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
          </button>
        ))}
      </div>
      <div className="p-3 border-t border-border">
        <p className="text-xs text-muted text-center">Sessions reset on refresh</p>
      </div>
    </div>
  )
}

export default function ContentCreator() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { state: sseState, run: runSSE, reset: resetSSE } = useSSE(6)
  const activeSession = sessions.find(s => s.id === activeId) || null

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [activeSession?.messages])

  useEffect(() => {
    if (!activeId) return
    if (sseState.status === 'running') {
      const runningStage = sseState.stages.find(s => s.status === 'running')
      if (runningStage) {
        const msg = STAGE_NAMES[runningStage.stage] || `Stage ${runningStage.stage}...`
        setSessions(prev => prev.map(s => {
          if (s.id !== activeId) return s
          const msgs = s.messages.filter(m => !m.isProgress)
          return { ...s, messages: [...msgs, { id: genId(), role: 'system' as const, content: msg, timestamp: new Date(), isProgress: true }] }
        }))
      }
    }
    if (sseState.status === 'complete' && sseState.result) {
      const result = sseState.result
      const brandName = result.brand_name as string
      const posts = (result.generated_posts as unknown[])?.length || 0
      const campaigns = (result.campaign_ideas as unknown[])?.length || 0
      setSessions(prev => prev.map(s => s.id === activeId ? { ...s, phase: 'chat' as const, result, brandName: brandName || s.brandName, messages: [...s.messages.filter(m => !m.isProgress), { id: genId(), role: 'assistant' as const, content: '', timestamp: new Date(), isResults: true, result }] } : s))
      addBotMessage(activeId, `Your content pack for **${brandName}** is ready! 🎉\n\nGenerated **${posts} posts** and **${campaigns} campaign ideas**.\n\nWhat would you like to do next?`)
      setTimeout(() => addSuggestions(activeId), 300)
    }
    if (sseState.status === 'error') {
      addBotMessage(activeId, `Something went wrong: ${sseState.error}. Please try again.`)
      setSessions(prev => prev.map(s => s.id === activeId ? { ...s, phase: 'intake' as const } : s))
    }
  }, [sseState.status, JSON.stringify(sseState.stages.map(s => s.status))])

  function createSession(): string {
    const id = genId()
    const session: Session = {
      id, brandName: '', createdAt: new Date(),
      messages: [{ id: genId(), role: 'assistant', content: WELCOME, timestamp: new Date() }],
      result: null, config: null, phase: 'intake', extractedFields: {},
    }
    setSessions(prev => [session, ...prev])
    setActiveId(id)
    resetSSE()
    return id
  }

  function addBotMessage(sessionId: string, content: string) {
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, messages: [...s.messages, { id: genId(), role: 'assistant' as const, content, timestamp: new Date() }] } : s))
  }

  function addSuggestions(sessionId: string) {
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, messages: [...s.messages, { id: genId(), role: 'assistant' as const, content: SUGGESTIONS.map((sg, i) => `${i + 1}. ${sg}`).join('\n'), timestamp: new Date(), isSuggestion: true }] } : s))
  }

  async function sendMessage(text?: string) {
    const messageText = text || input.trim()
    if (!messageText || isTyping) return
    let sessionId = activeId
    if (!sessionId) { sessionId = createSession() }
    setInput('')
    setIsTyping(true)
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, messages: [...s.messages, { id: genId(), role: 'user' as const, content: messageText, timestamp: new Date() }] } : s))
    const session = sessions.find(s => s.id === sessionId)
    const phase = session?.phase || 'intake'
    try {
      if (phase === 'chat' && session?.result && session?.config) {
        const history = (session.messages || []).filter(m => m.role === 'user' || m.role === 'assistant').map(m => ({ role: m.role, content: m.content }))
        const res = await fetch('http://localhost:8000/api/content/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: messageText, conversation_history: history, output: session.result, config: session.config, mode: 'followup' }) })
        const data = await res.json()
        addBotMessage(sessionId!, data.reply)
      } else {
        const currentFields = session?.extractedFields || {}
        const res = await fetch('http://localhost:8000/api/content/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: messageText, conversation_history: [{ role: 'system', extracted: currentFields }], mode: 'intake' }) })
        const data = await res.json()
        if (data.extracted) {
          setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, extractedFields: data.extracted, brandName: data.extracted.brand_name || s.brandName } : s))
        }
        if (data.ready && data.extracted) {
          addBotMessage(sessionId!, data.reply)
          setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, phase: 'running' as const, config: data.extracted, brandName: data.extracted.brand_name } : s))
          runSSE('http://localhost:8000/api/content/run', data.extracted)
        } else {
          addBotMessage(sessionId!, data.reply)
        }
      }
    } catch {
      addBotMessage(sessionId!, 'Sorry, something went wrong. Please try again.')
    } finally {
      setIsTyping(false)
    }
  }

  useEffect(() => { if (sessions.length === 0) createSession() }, [])

  return (
    <div className="h-screen flex flex-col bg-cream font-body overflow-hidden">
      <Navbar />
      <div className="flex flex-1 overflow-hidden pt-16">
        <Sidebar sessions={sessions} activeId={activeId} onSelect={id => { setActiveId(id); resetSSE() }} onNew={() => createSession()} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-6 py-3 border-b border-border flex items-center justify-between bg-cream/80 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <button onClick={() => navigate('/')} className="text-xs text-muted hover:text-charcoal transition-colors flex items-center gap-1">
                <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M10 7H4M6 4L3 7l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                Home
              </button>
              {activeSession?.brandName && (<>
                <span className="text-muted/40 text-xs">·</span>
                <span className="text-sm font-medium text-charcoal">{activeSession.brandName}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${activeSession.phase === 'chat' ? 'bg-green-100 text-green-700' : activeSession.phase === 'running' ? 'bg-amber-100 text-amber-700' : 'bg-cream-dark text-muted'}`}>
                  {activeSession.phase === 'chat' ? 'Ready' : activeSession.phase === 'running' ? 'Generating...' : 'Setting up'}
                </span>
              </>)}
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${activeSession?.phase === 'running' ? 'bg-amber-400 animate-pulse' : activeSession?.phase === 'chat' ? 'bg-green-400' : 'bg-border'}`} />
              <span className="text-xs text-muted">AI Content Strategist</span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="max-w-2xl mx-auto">
              {activeSession?.phase === 'chat' && activeSession?.result && false && <ResultsSummary result={activeSession.result} />}
              {(activeSession?.messages || []).filter(m => !m.isProgress).map(msg => (
                msg.isResults && msg.result ? (
                  <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-4 flex justify-start">
                    <div className="w-7 h-7 rounded-full bg-coral flex-shrink-0 flex items-center justify-center mr-2 mt-0.5">
                      <span className="text-white text-xs font-bold font-display">X</span>
                    </div>
                    <div className="flex-1 max-w-[85%]">
                      <ResultsSummary result={msg.result} />
                    </div>
                  </motion.div>
                ) : msg.isSuggestion ? (
                  <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-4 ml-9 flex flex-wrap gap-2">
                    {msg.content.split('\n').filter(Boolean).map((line, i) => {
                      const match = line.match(/^\d+\.\s+(.+)$/)
                      return match ? (
                        <button key={i} onClick={() => sendMessage(match[1])} className="text-xs border border-border hover:border-charcoal text-muted hover:text-charcoal px-3 py-1.5 rounded-full transition-colors">
                          {match[1]}
                        </button>
                      ) : null
                    })}
                  </motion.div>
                ) : <MessageBubble key={msg.id} msg={msg} />
              ))}
              {activeSession?.messages.find(m => m.isProgress) && (
                <div className="flex justify-start mb-3">
                  <div className="flex items-center gap-2 text-xs text-muted bg-cream-dark px-3 py-2 rounded-full">
                    <div className="w-1.5 h-1.5 rounded-full bg-coral animate-pulse" />
                    {activeSession.messages.find(m => m.isProgress)?.content}
                  </div>
                </div>
              )}
              {isTyping && (
                <div className="flex justify-start mb-4">
                  <div className="w-7 h-7 rounded-full bg-coral flex-shrink-0 flex items-center justify-center mr-2"><span className="text-white text-xs font-bold font-display">X</span></div>
                  <div className="bg-white border border-border px-4 py-3 rounded-2xl rounded-tl-sm flex gap-1 items-center">
                    {[0, 1, 2].map(i => <div key={i} className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />)}
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>
          <div className="px-6 py-4 border-t border-border bg-cream/80 backdrop-blur-sm">
            <div className="max-w-2xl mx-auto">
              <div className="flex gap-3 items-end">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                  placeholder={activeSession?.phase === 'chat' ? 'Ask anything about your content...' : 'Describe your brand...'}
                  rows={1}
                  disabled={activeSession?.phase === 'running'}
                  className="flex-1 px-4 py-3 rounded-xl border border-border bg-white text-charcoal text-sm placeholder:text-muted/50 focus:outline-none focus:border-charcoal transition-colors resize-none disabled:opacity-50"
                  style={{ minHeight: '44px', maxHeight: '120px' }}
                  onInput={e => { const t = e.target as HTMLTextAreaElement; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 120) + 'px' }}
                />
                <button
                  onClick={() => sendMessage()}
                  disabled={!input.trim() || isTyping || activeSession?.phase === 'running'}
                  className={`flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${input.trim() && !isTyping && activeSession?.phase !== 'running' ? 'bg-coral hover:bg-coral-dark text-white' : 'bg-border text-muted cursor-not-allowed'}`}
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 8h12M10 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </button>
              </div>
              <p className="text-xs text-muted mt-2 text-center">Enter to send · Shift+Enter for new line</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}