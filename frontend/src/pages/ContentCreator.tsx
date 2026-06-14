import { useState, useRef, useEffect, Component } from 'react'
import type { ReactNode } from 'react'
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

// Safely render any value (string, number, object, array) as text.
// Prevents "Objects are not valid as a React child" crashes when
// backend fields don't exactly match the expected shape.
const renderAsText = (value: unknown): string => {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(renderAsText).join('\n')
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

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

// ── Types matching content_state.py / content_creator_agent.py exactly ─────

interface PostEntry {
  post_number?: number
  week?: number
  day_of_week?: string
  platform: string
  content_pillar?: string
  content_type: string
  topic: string
  caption: string
  hashtags: string[]
  cta?: string
  reel_script?: string | null   // plain text, only when content_type === "Reel"
  evidence_sources?: string[]
}

interface CampaignIdea {
  name: string
  objective: string
  duration_days: number
  platforms?: string[]
  core_message?: string
  content_formats?: string[]
  hook?: string
  cta?: string
  kpis?: string[]
  evidence_sources?: string[]
}

interface AnniversaryCampaign {
  year_milestone?: number
  anniversary_date?: string
  campaign_name?: string
  theme?: string
  key_message?: string
  content_pieces?: string[]
  platforms?: string[]
  hashtag?: string
  cta?: string
  evidence_sources?: string[]
}

interface ContentPillar {
  name: string
  description?: string
  percentage: number
}

interface CalendarSlot {
  post_number?: number
  week?: number
  day_of_week?: string
  platform: string
  content_pillar?: string
  content_type: string
  topic?: string
}

// Catches render errors inside ResultsSummary so a bad/unexpected field
// shows a fallback card instead of white-screening the whole chat session.
class ResultsErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error: unknown) {
    console.error('ResultsSummary render error:', error)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-white border border-border rounded-2xl overflow-hidden mb-4 px-4 py-3">
          <p className="text-sm text-charcoal font-medium">Content pack generated</p>
          <p className="text-xs text-muted mt-1">
            Some result details couldn't be displayed here, but your content was generated successfully.
            You can ask the assistant directly for posts, captions, or campaigns.
          </p>
        </div>
      )
    }
    return this.props.children
  }
}

function ResultsSummary({ result }: { result: Record<string, unknown> }) {
  const posts = (result.generated_posts as PostEntry[]) || []
  const campaigns = (result.campaign_ideas as CampaignIdea[]) || []
  const pillars = (result.content_pillars as ContentPillar[]) || []
  const calendar = (result.content_calendar as CalendarSlot[]) || []
  const brandProfile = result.brand_profile as Record<string, unknown> | undefined
  const contentStrategy = result.content_strategy as Record<string, unknown> | undefined
  const anniversary = result.anniversary_campaign as AnniversaryCampaign | undefined
  const hashtagBank = result.hashtag_bank as Record<string, Record<string, string[]>> | undefined
  const ctaBank = (result.cta_bank as string[]) || []
  const trendingTopics = (result.trending_topics as string[]) || []
  const localTrends = (result.local_trends as string[]) || []
  const status = result.status as string | undefined

  const [expanded, setExpanded] = useState<string | null>(null)
  const [expandedPost, setExpandedPost] = useState<number | null>(null)

  const toggle = (key: string) => setExpanded(expanded === key ? null : key)

  return (
    <div className="bg-white border border-border rounded-2xl overflow-hidden mb-4">
      <div className="bg-charcoal px-4 py-3 flex items-center justify-between">
        <span className="text-white text-sm font-medium font-display">Content pack ready</span>
        <div className="flex items-center gap-2">
          {status && status !== 'success' && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${status === 'partial' ? 'bg-amber-500/20 text-amber-300' : 'bg-red-500/20 text-red-300'}`}>
              {status}
            </span>
          )}
          <span className="text-white/50 text-xs">{posts.length} posts · {campaigns.length} campaigns</span>
        </div>
      </div>


      {/* Brand Profile */}
      {brandProfile && Object.keys(brandProfile).length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('profile')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Brand profile</p>
            <span className="text-xs text-muted">{expanded === 'profile' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'profile' && (
            <div className="mt-3 space-y-2 text-xs text-charcoal">
              {typeof brandProfile.summary === 'string' && <p className="whitespace-pre-wrap">{brandProfile.summary}</p>}
              <div className="grid grid-cols-2 gap-2 mt-2">
                {brandProfile.brand_age_years != null && (
                  <div><span className="text-muted">Brand age: </span>{String(brandProfile.brand_age_years)} yrs</div>
                )}
                {typeof brandProfile.brand_tone === 'string' && (
                  <div><span className="text-muted">Tone: </span>{brandProfile.brand_tone}</div>
                )}
                {typeof brandProfile.content_language === 'string' && (
                  <div><span className="text-muted">Language: </span>{brandProfile.content_language}</div>
                )}
              </div>
              {typeof brandProfile.target_audience === 'string' && (
                <div><span className="text-muted">Target audience: </span><span className="whitespace-pre-wrap">{brandProfile.target_audience}</span></div>
              )}
              {typeof brandProfile.unique_value_prop === 'string' && (
                <div><span className="text-muted">Value prop: </span><span className="whitespace-pre-wrap">{brandProfile.unique_value_prop}</span></div>
              )}
              {typeof brandProfile.market_positioning === 'string' && (
                <div><span className="text-muted">Market position: </span><span className="whitespace-pre-wrap">{brandProfile.market_positioning}</span></div>
              )}
              {typeof brandProfile.cultural_context === 'string' && (
                <div><span className="text-muted">Cultural context: </span><span className="whitespace-pre-wrap">{brandProfile.cultural_context}</span></div>
              )}
              {Array.isArray(brandProfile.audience_pain_points) && brandProfile.audience_pain_points.length > 0 && (
                <div>
                  <span className="text-muted">Pain points:</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    {(brandProfile.audience_pain_points as string[]).map((pp, i) => <li key={i}>{pp}</li>)}
                  </ul>
                </div>
              )}
              {Array.isArray(brandProfile.content_opportunities) && brandProfile.content_opportunities.length > 0 && (
                <div>
                  <span className="text-muted">Content opportunities:</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    {(brandProfile.content_opportunities as string[]).map((co, i) => <li key={i}>{co}</li>)}
                  </ul>
                </div>
              )}
              {Array.isArray(brandProfile.evidence_used) && brandProfile.evidence_used.length > 0 && (
                <div>
                  <span className="text-muted">Evidence used ({(brandProfile.evidence_used as string[]).length}):</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5 text-muted">
                    {(brandProfile.evidence_used as string[]).map((ev, i) => <li key={i}>{ev}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Content Strategy */}
      {contentStrategy && Object.keys(contentStrategy).length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('strategy')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Content strategy</p>
            <span className="text-xs text-muted">{expanded === 'strategy' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'strategy' && (
            <div className="mt-3 space-y-2 text-xs text-charcoal">
              {typeof contentStrategy.strategic_goal === 'string' && (
                <div><span className="text-muted">Strategic goal: </span><span className="whitespace-pre-wrap">{contentStrategy.strategic_goal}</span></div>
              )}
              {typeof contentStrategy.audience_insight === 'string' && (
                <div><span className="text-muted">Audience insight: </span><span className="whitespace-pre-wrap">{contentStrategy.audience_insight}</span></div>
              )}
              {typeof contentStrategy.confidence === 'string' && (
                <div><span className="text-muted">Confidence: </span>{contentStrategy.confidence}</div>
              )}
              {contentStrategy.content_mix && typeof contentStrategy.content_mix === 'object' && (
                <div>
                  <span className="text-muted">Content mix:</span>
                  <div className="space-y-1 mt-1">
                    {Object.entries(contentStrategy.content_mix as Record<string, number>).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span>{k}</span><span className="text-coral">{v}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {contentStrategy.platform_strategy && typeof contentStrategy.platform_strategy === 'object' && (
                <div>
                  <span className="text-muted">Platform strategy:</span>
                  <div className="space-y-1 mt-1">
                    {Object.entries(contentStrategy.platform_strategy as Record<string, unknown>).map(([platform, strat]) => (
                      <div key={platform}>
                        <span className="font-medium">{platform}: </span>
                        {typeof strat === 'object' && strat !== null
                          ? Object.entries(strat as Record<string, unknown>).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')
                          : String(strat)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Content Pillars */}
      {pillars.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <p className="text-xs text-muted uppercase tracking-wider mb-2">Content pillars</p>
          <div className="space-y-2">
            {pillars.map((p, i) => (
              <div key={i}>
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="text-charcoal font-medium">{p.name}</span>
                  <span className="text-coral">{p.percentage}%</span>
                </div>
                <div className="h-1 bg-border rounded-full overflow-hidden">
                  <div className="h-full bg-coral rounded-full" style={{ width: `${p.percentage}%` }} />
                </div>
                {p.description && <p className="text-xs text-muted mt-1 whitespace-pre-wrap">{p.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Calendar Overview */}
      {calendar.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('calendar')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Calendar overview ({calendar.length})</p>
            <span className="text-xs text-muted">{expanded === 'calendar' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'calendar' && (
            <div className="mt-3 space-y-3">
              {/* By platform */}
              <div className="text-xs text-charcoal">
                <span className="text-muted">By platform:</span>
                <div className="space-y-1 mt-1">
                  {Object.entries(
                    calendar.reduce((acc, slot) => {
                      acc[slot.platform] = (acc[slot.platform] || 0) + 1
                      return acc
                    }, {} as Record<string, number>)
                  ).map(([platform, count]) => (
                    <div key={platform} className="flex justify-between">
                      <span>{platform}</span><span className="text-coral">{count} posts</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* By pillar */}
              <div className="text-xs text-charcoal">
                <span className="text-muted">By pillar:</span>
                <div className="space-y-1 mt-1">
                  {Object.entries(
                    calendar.reduce((acc, slot) => {
                      const key = slot.content_pillar || 'Unassigned'
                      acc[key] = (acc[key] || 0) + 1
                      return acc
                    }, {} as Record<string, number>)
                  ).map(([pillar, count]) => (
                    <div key={pillar} className="flex justify-between">
                      <span>{pillar}</span><span className="text-coral">{count} posts</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* By week */}
              <div className="text-xs text-charcoal">
                <span className="text-muted">By week:</span>
                <div className="space-y-1 mt-1">
                  {Object.entries(
                    calendar.reduce((acc, slot) => {
                      const key = slot.week != null ? `Week ${slot.week}` : 'Unscheduled'
                      acc[key] = (acc[key] || 0) + 1
                      return acc
                    }, {} as Record<string, number>)
                  ).sort(([a], [b]) => a.localeCompare(b)).map(([week, count]) => (
                    <div key={week} className="flex justify-between">
                      <span>{week}</span><span className="text-coral">{count} posts</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* Full slot list */}
              <div className="max-h-64 overflow-y-auto space-y-1.5 mt-2">
                {calendar.map((slot, i) => (
                  <div key={i} className="border border-border rounded-lg p-2 text-xs flex flex-wrap items-center gap-2">
                    {slot.post_number != null && <span className="text-muted font-medium">#{slot.post_number}</span>}
                    {slot.week != null && slot.day_of_week && <span className="text-muted">Week {slot.week} {slot.day_of_week}</span>}
                    <span className="bg-cream-dark text-muted px-2 py-0.5 rounded">{slot.platform}</span>
                    <span className="bg-cream-dark text-muted px-2 py-0.5 rounded">{slot.content_type}</span>
                    {slot.content_pillar && <span className="bg-cream-dark text-muted px-2 py-0.5 rounded">{slot.content_pillar}</span>}
                    {slot.topic && <span className="text-charcoal flex-1 min-w-full sm:min-w-0">{slot.topic}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Posts */}
      {posts.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('posts')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Posts ({posts.length})</p>
            <span className="text-xs text-muted">{expanded === 'posts' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'posts' && (
            <div className="mt-3 space-y-3 max-h-96 overflow-y-auto">
              {posts.map((p, i) => (
                <div key={i} className="border border-border rounded-lg p-3">
                  <div className="flex gap-2 mb-1 flex-wrap items-center">
                    {p.post_number != null && <span className="text-xs text-muted font-medium">#{p.post_number}</span>}
                    {p.week != null && p.day_of_week && <span className="text-xs text-muted">Week {p.week} {p.day_of_week}</span>}
                    <span className="text-xs bg-cream-dark text-muted px-2 py-0.5 rounded">{p.platform}</span>
                    <span className="text-xs bg-cream-dark text-muted px-2 py-0.5 rounded">{p.content_type}</span>
                    {p.content_pillar && <span className="text-xs bg-cream-dark text-muted px-2 py-0.5 rounded">{p.content_pillar}</span>}
                  </div>
                  <p className="text-xs font-medium text-charcoal mb-1">{p.topic}</p>
                  <p className="text-xs text-muted whitespace-pre-wrap">{p.caption}</p>
                  {p.hashtags?.length > 0 && <p className="text-xs text-coral mt-1">{p.hashtags.join(' ')}</p>}
                  {p.cta && (
                    <p className="text-xs text-charcoal mt-2"><span className="text-muted font-medium">CTA: </span>{renderAsText(p.cta)}</p>
                  )}
                  {p.reel_script && (
                    <div className="mt-2">
                      <button onClick={() => setExpandedPost(expandedPost === i ? null : i)} className="text-xs text-coral underline">
                        {expandedPost === i ? 'Hide reel script' : 'Show reel script'}
                      </button>
                      {expandedPost === i && (
                        <div className="mt-2 bg-cream-dark rounded-lg p-2 text-xs text-charcoal whitespace-pre-wrap">
                          {renderAsText(p.reel_script)}
                        </div>
                      )}
                    </div>
                  )}
                  {p.evidence_sources?.length ? (
                    <p className="text-xs text-muted mt-2">Evidence: {p.evidence_sources.map(renderAsText).join(', ')}</p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Campaigns */}
      {campaigns.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('campaigns')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Campaigns ({campaigns.length})</p>
            <span className="text-xs text-muted">{expanded === 'campaigns' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'campaigns' && (
            <div className="mt-3 space-y-2">
              {campaigns.map((c, i) => (
                <div key={i} className="border border-border rounded-lg p-3 space-y-1">
                  <p className="text-xs font-medium text-charcoal">{c.name}</p>
                  <p className="text-xs text-muted">
                    {c.duration_days} days{c.platforms?.length ? ` · ${c.platforms.join(', ')}` : ''}
                    {c.content_formats?.length ? ` · ${c.content_formats.join(', ')}` : ''}
                  </p>
                  <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">Objective: </span>{c.objective}</p>
                  {c.core_message && <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">Core message: </span>{c.core_message}</p>}
                  {c.hook && <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">Hook: </span>{c.hook}</p>}
                  {c.cta && <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">CTA: </span>{c.cta}</p>}
                  {c.kpis?.length ? (
                    <div className="text-xs text-charcoal">
                      <span className="text-muted">KPIs:</span>
                      <ul className="list-disc list-inside mt-1 space-y-0.5">
                        {c.kpis.map((k, ki) => <li key={ki}>{k}</li>)}
                      </ul>
                    </div>
                  ) : null}
                  {c.evidence_sources?.length ? (
                    <p className="text-xs text-muted">Evidence: {c.evidence_sources.join(', ')}</p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Anniversary Campaign */}
      {anniversary && Object.keys(anniversary).length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('anniversary')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">🎉 Anniversary campaign</p>
            <span className="text-xs text-muted">{expanded === 'anniversary' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'anniversary' && (
            <div className="mt-3 border border-border rounded-lg p-3 space-y-1">
              {anniversary.campaign_name && <p className="text-xs font-medium text-charcoal">{anniversary.campaign_name}</p>}
              <p className="text-xs text-muted">
                {anniversary.anniversary_date ? `Date: ${anniversary.anniversary_date}` : ''}
                {anniversary.year_milestone ? ` · ${anniversary.year_milestone}-year milestone` : ''}
                {anniversary.platforms?.length ? ` · ${anniversary.platforms.join(', ')}` : ''}
              </p>
              {anniversary.theme && <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">Theme: </span>{anniversary.theme}</p>}
              {anniversary.key_message && <p className="text-xs text-charcoal whitespace-pre-wrap"><span className="text-muted">Key message: </span>{anniversary.key_message}</p>}
              {anniversary.content_pieces?.length ? (
                <div className="text-xs text-charcoal">
                  <span className="text-muted">Content pieces:</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    {anniversary.content_pieces.map((cp, i) => <li key={i}>{cp}</li>)}
                  </ul>
                </div>
              ) : null}
              {anniversary.hashtag && <p className="text-xs text-coral">{anniversary.hashtag}</p>}
              {anniversary.cta && <p className="text-xs text-charcoal"><span className="text-muted">CTA: </span>{anniversary.cta}</p>}
            </div>
          )}
        </div>
      )}

      {/* Hashtag Bank */}
      {hashtagBank && Object.keys(hashtagBank).length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('hashtags')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Hashtag bank</p>
            <span className="text-xs text-muted">{expanded === 'hashtags' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'hashtags' && (
            <div className="mt-3 space-y-3">
              {Object.entries(hashtagBank).map(([platform, pillarMap]) => (
                <div key={platform}>
                  <p className="text-xs font-medium text-charcoal mb-1">{platform}</p>
                  <div className="space-y-1">
                    {Object.entries(pillarMap || {}).map(([pillar, tags]) => (
                      <div key={pillar} className="text-xs">
                        <span className="text-muted">{pillar}: </span>
                        <span className="text-coral">{Array.isArray(tags) ? tags.join(' ') : String(tags)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* CTA Bank */}
      {ctaBank.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <button onClick={() => toggle('ctabank')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">CTA bank ({ctaBank.length})</p>
            <span className="text-xs text-muted">{expanded === 'ctabank' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'ctabank' && (
            <ul className="mt-3 space-y-1 text-xs text-charcoal list-decimal list-inside">
              {ctaBank.map((cta, i) => <li key={i}>{cta}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Trending topics & local trends */}
      {(trendingTopics.length > 0 || localTrends.length > 0) && (
        <div className="px-4 py-3">
          <button onClick={() => toggle('trends')} className="flex items-center justify-between w-full text-left">
            <p className="text-xs text-muted uppercase tracking-wider">Trends used</p>
            <span className="text-xs text-muted">{expanded === 'trends' ? '▲' : '▼'}</span>
          </button>
          {expanded === 'trends' && (
            <div className="mt-3 space-y-2 text-xs text-charcoal">
              {trendingTopics.length > 0 && (
                <div>
                  <span className="text-muted">Trending topics:</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    {trendingTopics.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                </div>
              )}
              {localTrends.length > 0 && (
                <div>
                  <span className="text-muted">Local trends:</span>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    {localTrends.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                </div>
              )}
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
      setSessions(prev => prev.map(s => s.id === activeId ? { ...s, phase: 'chat' as const, result, brandName: brandName || s.brandName, messages: [...s.messages.filter(m => !m.isProgress), { id: genId(), role: 'assistant' as const, content: '', timestamp: new Date(), isResults: true, result }]} : s))
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
                      <ResultsErrorBoundary>
                        <ResultsSummary result={msg.result} />
                      </ResultsErrorBoundary>
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