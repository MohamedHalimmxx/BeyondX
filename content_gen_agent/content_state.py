from __future__ import annotations

import sys
from typing import Any, Optional

# Pydantic v2 requires typing_extensions.TypedDict on Python < 3.12
if sys.version_info >= (3, 12):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Sub-structures (plain dicts kept simple for LangGraph serialisation)
# ---------------------------------------------------------------------------

class PostEntry(TypedDict, total=False):
    """A single post slot inside the monthly content calendar."""
    post_number: int           # Sequential number within the month (1-N)
    week: int                  # Calendar week of the month (1-4 / 1-5)
    day_of_week: str           # e.g. "Monday", "Wednesday"
    platform: str              # e.g. "Instagram", "TikTok"
    content_pillar: str        # Which pillar this post belongs to
    content_type: str          # "Reel", "Carousel", "Static", "Story", etc.
    topic: str                 # Specific post topic / angle
    caption: str               # Full platform-ready caption
    hashtags: list[str]        # Platform-specific hashtag set
    cta: str                   # Call-to-action line
    reel_script: Optional[str] # Populated only when content_type == "Reel"
    evidence_sources: list[str]# URLs / titles that grounded this post


class ContentPillar(TypedDict, total=False):
    """A single content pillar with its rationale and evidence."""
    name: str               # Pillar label, e.g. "Education", "Behind the Scenes"
    description: str        # What this pillar covers and why it matters
    percentage: int         # Share of monthly posts allocated (must sum to 100)
    post_types: list[str]   # Recommended formats for this pillar
    evidence: list[str]     # Trend / research URLs that justify this pillar


class CampaignIdea(TypedDict, total=False):
    """A single campaign concept."""
    name: str                  # Campaign title
    objective: str             # Business / awareness objective
    duration_days: int         # Suggested run length
    platforms: list[str]       # Target platforms
    core_message: str          # One-sentence campaign message
    content_formats: list[str] # Content types used in the campaign
    hook: str                  # Opening hook / attention grabber
    cta: str                   # Primary call-to-action
    kpis: list[str]            # Success metrics
    evidence_sources: list[str]# Trend data or competitor evidence backing this


class AnniversaryCampaign(TypedDict, total=False):
    """Special campaign tied to the brand's foundation anniversary."""
    year_milestone: int          # Which anniversary year this targets
    anniversary_date: str        # ISO date string  "YYYY-MM-DD"
    campaign_name: str
    theme: str                   # Emotional / creative theme
    key_message: str
    content_pieces: list[str]    # List of content pieces to produce
    platforms: list[str]
    hashtag: str                 # Dedicated campaign hashtag
    cta: str
    evidence_sources: list[str]


# ---------------------------------------------------------------------------
# Master State
# ---------------------------------------------------------------------------

class ContentState(TypedDict, total=False):
    """
    Complete state for the Content Creator Agent workflow.

    Lifecycle
    ---------
    1. Agent initialises the USER INPUT fields and invokes the graph.
    2. Each node reads what it needs and writes to its own OUTPUT fields.
    3. After the graph finishes, the agent reads the FINAL OUTPUT fields.

    Field-ownership legend
    ----------------------
    [IN]       Set by the agent before graph invocation; never modified by nodes.
    [CTX]      Produced by brand_context_node.
    [TREND]    Produced by trend_research_node.
    [STRAT]    Produced by content_strategy_node.
    [CAL]      Produced by calendar_builder_node.
    [GEN]      Produced by content_generator_node.
    [CAMP]     Produced by campaign_generator_node.
    [SYS]      Internal / cross-cutting; managed by the graph or agent.
    """

    # ------------------------------------------------------------------
    # [IN] User-supplied inputs
    # ------------------------------------------------------------------

    brand_name: str
    """Legal or operating name of the brand (e.g. 'Acme Corp')."""

    industry: str
    """Industry vertical the brand operates in (e.g. 'Specialty Coffee')."""

    country: str
    """Country where the brand is headquartered or primarily active."""

    city: str
    """City for hyper-local trend research and audience context."""

    foundation_date: str
    """
    ISO date string 'YYYY-MM-DD'.
    Used to calculate brand age, upcoming anniversaries, and milestone
    campaign timing.
    """

    social_platforms: list[str]
    """
    Platforms the brand wants content for.
    Accepted values: 'Instagram', 'TikTok', 'LinkedIn', 'X', 'Facebook',
    'YouTube Shorts', 'Pinterest', 'Threads'.
    """

    posts_per_month: int
    """
    Total number of posts to generate across ALL platforms per month.
    Calendar Builder distributes these across platforms and weeks.
    """

    # ------------------------------------------------------------------
    # [CTX] Brand Context Node outputs
    # ------------------------------------------------------------------

    brand_profile: Optional[dict[str, Any]]
    """
    Structured profile synthesised by brand_context_node.
    Shape: {
        'summary': str,          # 2-3 sentence brand overview
        'brand_age_years': int,  # Computed from foundation_date
        'target_audience': str,  # Inferred primary audience segment
        'brand_tone': str,       # e.g. 'Professional & Warm'
        'unique_value_prop': str,# One-line differentiator
        'content_language': str, # Primary language for captions
        'cultural_context': str, # Local nuances for city/country
    }
    """

    brand_context_evidence: Optional[list[str]]
    """
    List of source URLs / document titles retrieved during brand context
    research. Must be non-empty before brand_profile is accepted as valid.
    """

    # ------------------------------------------------------------------
    # [TREND] Trend Research Node outputs
    # ------------------------------------------------------------------

    trend_research_results: Optional[list[dict[str, Any]]]
    """
    Raw search results from Tavily.
    Each item shape: {
        'query': str,    # The search query that produced this result
        'url': str,      # Source URL
        'title': str,    # Page / article title
        'snippet': str,  # Relevant excerpt
        'score': float,  # Tavily relevance score
    }
    All downstream nodes MUST reference this list when making
    evidence-grounded claims.
    """

    trending_topics: Optional[list[str]]
    """
    Curated list of trend labels extracted and validated from
    trend_research_results. Never assumed — each item must map
    back to at least one entry in trend_research_results.
    Example: ['AI-powered skincare', 'slow living', '#ThriftFlip'].
    """

    competitor_insights: Optional[list[dict[str, str]]]
    """
    Observed patterns from competitor / industry content found during
    trend research.
    Each item shape: {
        'observation': str,  # What was found
        'source': str,       # URL or title
    }
    """

    local_trends: Optional[list[str]]
    """
    City/country-specific trends extracted from Tavily results.
    Kept separate from global trends so nodes can apply them with
    the correct geographic context.
    """

    # ------------------------------------------------------------------
    # [STRAT] Content Strategy Node outputs
    # ------------------------------------------------------------------

    content_strategy: Optional[dict[str, Any]]
    """
    High-level strategic document produced by content_strategy_node.
    Shape: {
        'strategic_goal': str,           # Primary 30-day content objective
        'audience_insight': str,         # Evidence-backed audience behaviour note
        'platform_strategy': dict,       # Per-platform posting rationale
        'content_mix': dict,             # Format breakdown (%, e.g. 40% Reels)
        'posting_frequency': dict,       # Posts per platform per week
        'tone_guidelines': str,          # Caption voice rules
        'evidence_summary': str,         # 1-para synthesis of supporting research
    }
    """

    content_pillars: Optional[list[ContentPillar]]
    """
    3-5 thematic content pillars derived from strategy + trend evidence.
    Percentages across all pillars must sum to 100.
    Each pillar must cite at least one source from trend_research_results.
    """

    strategy_evidence_used: Optional[list[str]]
    """
    Subset of trend_research_results URLs that were explicitly used when
    building content_strategy and content_pillars. Audit trail.
    """

    # ------------------------------------------------------------------
    # [CAL] Calendar Builder Node outputs
    # ------------------------------------------------------------------

    content_calendar: Optional[list[PostEntry]]
    """
    Full monthly content calendar.
    Length == posts_per_month.
    Posts are distributed across platforms, weeks, and pillars
    according to content_strategy.
    Each PostEntry.evidence_sources must be populated at this stage
    with the trend URLs that informed the topic selection.
    """

    calendar_summary: Optional[dict[str, Any]]
    """
    Aggregate statistics over the generated calendar for QA.
    Shape: {
        'total_posts': int,
        'posts_by_platform': dict[str, int],
        'posts_by_pillar': dict[str, int],
        'posts_by_type': dict[str, int],
        'weeks_covered': int,
    }
    """

    # ------------------------------------------------------------------
    # [GEN] Content Generator Node outputs
    # ------------------------------------------------------------------

    generated_posts: Optional[list[PostEntry]]
    """
    content_calendar with captions, hashtags, CTAs, and reel_scripts
    fully populated. This is the primary deliverable of the workflow.
    Each item is a completed PostEntry — every optional field must be
    filled by content_generator_node before the post is accepted.
    """

    hashtag_bank: Optional[dict[str, list[str]]]
    """
    Master hashtag bank organised by platform and pillar for reuse.
    Shape: {
        '<platform>': {
            '<pillar>': ['#tag1', '#tag2', ...],
        }
    }
    Built and cached here so the campaign node can reuse them.
    """

    cta_bank: Optional[list[str]]
    """
    Reusable CTA library generated during content production.
    Each string is a complete, ready-to-use CTA sentence.
    """

    # ------------------------------------------------------------------
    # [CAMP] Campaign Generator Node outputs
    # ------------------------------------------------------------------

    campaign_ideas: Optional[list[CampaignIdea]]
    """
    2-4 standalone campaign concepts beyond the monthly calendar.
    Each campaign is fully self-contained and evidence-grounded.
    """

    anniversary_campaign: Optional[AnniversaryCampaign]
    """
    Special campaign tied to the brand's next or current anniversary
    milestone (computed from foundation_date).
    None if the next anniversary is more than 6 months away and no
    milestone year (5th, 10th, etc.) is approaching.
    """

    campaign_evidence_used: Optional[list[str]]
    """
    URLs from trend_research_results used to justify campaign choices.
    """

    # ------------------------------------------------------------------
    # [SYS] System / cross-cutting fields
    # ------------------------------------------------------------------

    errors: Optional[list[dict[str, str]]]
    """
    Non-fatal errors collected during the run.
    Each item shape: {
        'node': str,    # Which node raised the error
        'message': str, # Human-readable description
        'field': str,   # Which state field was affected
    }
    A non-empty list signals degraded output; the agent should surface
    these to the caller rather than silently returning partial content.
    """

    node_execution_log: Optional[list[dict[str, Any]]]
    """
    Ordered execution trace for debugging and observability.
    Each item shape: {
        'node': str,
        'status': 'success' | 'partial' | 'failed',
        'evidence_count': int,  # How many sources were used
        'duration_ms': int,
        'timestamp': str,       # ISO datetime
    }
    """

    generation_metadata: Optional[dict[str, Any]]
    """
    Top-level metadata about this workflow run.
    Shape: {
        'run_id': str,              # UUID for the run
        'model_used': str,          # LLM identifier (e.g. 'llama-3.3-70b-versatile')
        'total_evidence_sources': int,
        'generation_timestamp': str,# ISO datetime
        'posts_requested': int,
        'posts_generated': int,
    }
    """