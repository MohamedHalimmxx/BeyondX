from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from campaign_prompt import (
    ANNIVERSARY_WINDOW_MONTHS,
    CAMPAIGN_SYSTEM_PROMPT,
    MAX_CAMPAIGNS,
    MIN_CAMPAIGNS,
)
from content_state import (
    AnniversaryCampaign,
    CampaignIdea,
    ContentState,
    PostEntry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "campaign_generator_node"

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

LLM_TEMPERATURE: float = 0.3
LLM_MAX_TOKENS: int = 4096

# Maximum generated posts to surface in the brief (topic list only)
# — avoids overwhelming the context window with full caption text
MAX_CALENDAR_TOPICS_IN_PROMPT: int = 30

# Maximum trend results to include in the campaign brief
MAX_TREND_RESULTS_IN_PROMPT: int = 8

# Required fields for a valid CampaignIdea
CAMPAIGN_IDEA_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "objective",
        "duration_days",
        "platforms",
        "core_message",
        "content_formats",
        "hook",
        "content_arc",
        "cta",
        "hashtag",
        "kpis",
        "evidence_sources",
        "why_now",
    }
)

# Required fields for a valid AnniversaryCampaign
ANNIVERSARY_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "year_milestone",
        "anniversary_date",
        "campaign_name",
        "theme",
        "key_message",
        "content_arc",
        "content_pieces",
        "platforms",
        "hashtag",
        "cta",
        "community_activation",
        "evidence_sources",
    }
)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY3")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY3 environment variable is not set. "
            "Campaign generator node cannot call the LLM without it."
        )
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Anniversary date logic
# ---------------------------------------------------------------------------

def _compute_anniversary_context(
    foundation_date_str: str,
    brand_name: str,
) -> dict[str, Any]:
    """
    Computes anniversary metadata from the brand's foundation_date.

    Determines:
      - The brand's current age in years
      - The next anniversary date
      - The anniversary year (milestone number)
      - Whether the anniversary falls within ANNIVERSARY_WINDOW_MONTHS

    Parameters
    ----------
    foundation_date_str : str
        ISO date string 'YYYY-MM-DD' from ContentState.
    brand_name : str
        Used for log context.

    Returns
    -------
    dict[str, Any]
        {
            'foundation_date': date,
            'brand_age_years': int,
            'next_anniversary_date': date,
            'next_anniversary_year': int,  # e.g. 6 for the 6th anniversary
            'is_milestone_year': bool,     # 5th, 10th, 15th, 20th, 25th
            'within_window': bool,
            'months_until_anniversary': int,
        }
        Returns a minimal dict with within_window=False on parse failure.
    """
    try:
        foundation_date = datetime.strptime(
            foundation_date_str, "%Y-%m-%d"
        ).date()
    except ValueError:
        logger.warning(
            "[%s] Could not parse foundation_date '%s' | brand='%s'",
            NODE_NAME,
            foundation_date_str,
            brand_name,
        )
        return {"within_window": False, "brand_age_years": 0}

    today = date.today()

    # Compute brand age
    brand_age_years: int = (
        today.year - foundation_date.year
        - (
            (today.month, today.day)
            < (foundation_date.month, foundation_date.day)
        )
    )

    # Compute next anniversary date
    next_anniversary_year: int = brand_age_years + 1
    try:
        next_anniversary_date = foundation_date.replace(
            year=today.year
        )
        # If this year's anniversary already passed, use next year
        if next_anniversary_date < today:
            next_anniversary_date = foundation_date.replace(
                year=today.year + 1
            )
            next_anniversary_year = (
                next_anniversary_date.year - foundation_date.year
            )
    except ValueError:
        # Handle Feb 29 on non-leap years
        next_anniversary_date = foundation_date.replace(
            year=today.year + 1,
            day=28,
        )
        next_anniversary_year = (
            next_anniversary_date.year - foundation_date.year
        )

    # Months until anniversary
    delta = relativedelta(next_anniversary_date, today)
    months_until = delta.months + delta.years * 12

    within_window: bool = months_until <= ANNIVERSARY_WINDOW_MONTHS

    # Milestone years: 5, 10, 15, 20, 25, 30 ...
    is_milestone_year: bool = (next_anniversary_year % 5 == 0)

    logger.debug(
        "[%s] Anniversary context | brand='%s' | age=%d | "
        "next=%s (%d years) | months_until=%d | "
        "within_window=%s | milestone=%s",
        NODE_NAME,
        brand_name,
        brand_age_years,
        next_anniversary_date.isoformat(),
        next_anniversary_year,
        months_until,
        within_window,
        is_milestone_year,
    )

    return {
        "foundation_date": foundation_date,
        "brand_age_years": brand_age_years,
        "next_anniversary_date": next_anniversary_date,
        "next_anniversary_year": next_anniversary_year,
        "is_milestone_year": is_milestone_year,
        "within_window": within_window,
        "months_until_anniversary": months_until,
    }


# ---------------------------------------------------------------------------
# Human message builder
# ---------------------------------------------------------------------------

def _build_human_message(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    social_platforms: list[str],
    foundation_date: str,
    anniversary_context: dict[str, Any],
    brand_profile: dict[str, Any] | None,
    content_strategy: dict[str, Any],
    content_pillars: list[dict[str, Any]],
    trend_research_results: list[dict[str, Any]],
    trending_topics: list[str],
    local_trends: list[str],
    competitor_insights: list[dict[str, str]],
    generated_posts: list[PostEntry],
    cta_bank: list[str],
) -> str:
    """
    Constructs the campaign brief passed to the LLM.

    Sections assembled:
      - Brand parameters and anniversary context
      - Brand profile summary
      - Strategic goal and audience insight
      - Content pillars (names only — for non-duplication reference)
      - Existing calendar topics (for non-duplication reference)
      - Trending topics and local events (campaign opportunities)
      - Competitor insights (gap opportunities)
      - Top trend evidence (for evidence_sources citation)
      - CTA bank reference (for campaign CTA grounding)

    Parameters
    ----------
    See function signature — all params sourced from ContentState.

    Returns
    -------
    str
        Fully formatted campaign brief.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Anniversary block ─────────────────────────────────────────────────
    next_ann = anniversary_context.get("next_anniversary_date")
    next_ann_str = (
        next_ann.isoformat() if isinstance(next_ann, date) else "N/A"
    )
    milestone_flag = (
        " ⭐ MILESTONE YEAR"
        if anniversary_context.get("is_milestone_year")
        else ""
    )
    within_window = anniversary_context.get("within_window", False)

    anniversary_block = (
        f"  Foundation Date       : {foundation_date}\n"
        f"  Brand Age             : {anniversary_context.get('brand_age_years', 'N/A')} years\n"
        f"  Next Anniversary      : {next_ann_str} "
        f"(Year {anniversary_context.get('next_anniversary_year', 'N/A')})"
        f"{milestone_flag}\n"
        f"  Months Until          : {anniversary_context.get('months_until_anniversary', 'N/A')}\n"
        f"  Within Campaign Window: {'YES — generate anniversary campaign' if within_window else 'NO — set anniversary_campaign to null'}"
    )

    # ── Brand profile block ───────────────────────────────────────────────
    if brand_profile and not brand_profile.get("_parse_error"):
        profile_block = (
            f"  Summary          : {brand_profile.get('summary', 'N/A')}\n"
            f"  Target Audience  : {brand_profile.get('target_audience', 'N/A')}\n"
            f"  Brand Tone       : {brand_profile.get('brand_tone', 'N/A')}\n"
            f"  Unique Value Prop: {brand_profile.get('unique_value_prop', 'N/A')}\n"
            f"  Cultural Context : {brand_profile.get('cultural_context', 'N/A')}\n"
            f"  Content Language : {brand_profile.get('content_language', 'N/A')}"
        )
        pain_points = brand_profile.get("audience_pain_points", [])
        if pain_points:
            profile_block += (
                f"\n  Pain Points      : {'; '.join(pain_points)}"
            )
        opps = brand_profile.get("content_opportunities", [])
        if opps:
            profile_block += (
                f"\n  Opportunities    : {'; '.join(opps)}"
            )
    else:
        profile_block = "  Brand profile not available."

    # ── Strategic context ─────────────────────────────────────────────────
    strategic_goal = content_strategy.get(
        "strategic_goal", "Build brand presence."
    )
    audience_insight = content_strategy.get(
        "audience_insight", "N/A"
    )

    # ── Pillar names (non-duplication reference) ──────────────────────────
    pillar_names = [
        f"  • {p.get('name', 'Unknown')} ({p.get('percentage', 0)}%)"
        for p in content_pillars
    ]
    pillars_block = (
        "\n".join(pillar_names)
        if pillar_names
        else "  No pillar data available."
    )

    # ── Existing calendar topics (non-duplication reference) ──────────────
    calendar_topics = [
        post.get("topic", "")
        for post in generated_posts
        if post.get("topic")
    ][:MAX_CALENDAR_TOPICS_IN_PROMPT]

    topics_block = (
        "\n".join(f"  [{i+1}] {t}" for i, t in enumerate(calendar_topics))
        if calendar_topics
        else "  No calendar topics available."
    )

    # ── Trending topics (campaign opportunities) ──────────────────────────
    trending_block = (
        "\n".join(f"  • {t}" for t in trending_topics[:20])
        if trending_topics
        else "  No trending topics available."
    )

    # ── Local trends and events ───────────────────────────────────────────
    local_block = (
        "\n".join(f"  • {t}" for t in local_trends)
        if local_trends
        else "  No local events or trends available."
    )

    # ── Competitor insights ───────────────────────────────────────────────
    competitor_block = (
        "\n".join(
            f"  [{i+1}] {item.get('observation', 'N/A')}\n"
            f"       Source: {item.get('source', 'N/A')}"
            for i, item in enumerate(competitor_insights[:10])
        )
        if competitor_insights
        else "  No competitor insights available."
    )

    # ── Top evidence sources ──────────────────────────────────────────────
    synthesised = [
        r for r in trend_research_results
        if r.get("type") == "synthesised_finding"
    ]
    raw_scored = sorted(
        [
            r for r in trend_research_results
            if r.get("type") == "raw_search_result"
        ],
        key=lambda x: x.get("score", 0.0),
        reverse=True,
    )
    top_results = (
        synthesised + raw_scored
    )[:MAX_TREND_RESULTS_IN_PROMPT]

    evidence_lines: list[str] = []
    for i, r in enumerate(top_results, start=1):
        category = r.get("category", "general").replace("_", " ").upper()
        if r.get("type") == "synthesised_finding":
            label = (
                r.get("trend_name")
                or r.get("topic")
                or r.get("format_name")
                or r.get("event_name")
                or r.get("holiday_name")
                or r.get("hashtag")
                or r.get("moment")
                or "N/A"
            )
            description = (
                r.get("description")
                or r.get("context")
                or r.get("behavior_shift")
                or "N/A"
            )
            evidence_lines.append(
                f"  [{i}] [{category}] {label}\n"
                f"       Detail : {description[:200]}\n"
                f"       Source : {r.get('source', 'N/A')}"
            )
        else:
            evidence_lines.append(
                f"  [{i}] [{category}] {r.get('title', 'N/A')}\n"
                f"       Snippet: {r.get('snippet', 'N/A')[:200]}\n"
                f"       URL    : {r.get('url', 'N/A')}"
            )

    evidence_block = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "  No trend evidence available."
    )

    # ── CTA bank reference ────────────────────────────────────────────────
    cta_sample = cta_bank[:10] if cta_bank else []
    cta_block = (
        "\n".join(f"  • {cta}" for cta in cta_sample)
        if cta_sample
        else "  No CTA bank available."
    )

    message = (
        f"TODAY'S DATE: {today_str}\n"
        f"{'=' * 60}\n"
        f"BRAND PARAMETERS\n"
        f"{'=' * 60}\n"
        f"  Brand Name      : {brand_name}\n"
        f"  Industry        : {industry}\n"
        f"  Country         : {country}\n"
        f"  City            : {city}\n"
        f"  Social Platforms: {', '.join(social_platforms)}\n"
        f"{'=' * 60}\n"
        f"ANNIVERSARY CONTEXT\n"
        f"{'=' * 60}\n"
        f"{anniversary_block}\n"
        f"{'=' * 60}\n"
        f"BRAND PROFILE\n"
        f"{'=' * 60}\n"
        f"{profile_block}\n"
        f"{'=' * 60}\n"
        f"STRATEGIC CONTEXT\n"
        f"{'=' * 60}\n"
        f"  Strategic Goal   : {strategic_goal}\n"
        f"  Audience Insight : {audience_insight}\n"
        f"{'=' * 60}\n"
        f"EXISTING CONTENT PILLARS (do not duplicate)\n"
        f"{'=' * 60}\n"
        f"{pillars_block}\n"
        f"{'=' * 60}\n"
        f"EXISTING CALENDAR TOPICS "
        f"({len(calendar_topics)} shown — do not duplicate)\n"
        f"{'=' * 60}\n"
        f"{topics_block}\n"
        f"{'=' * 60}\n"
        f"TRENDING TOPICS (campaign opportunities)\n"
        f"{'=' * 60}\n"
        f"{trending_block}\n"
        f"{'=' * 60}\n"
        f"LOCAL EVENTS & CULTURAL MOMENTS\n"
        f"{'=' * 60}\n"
        f"{local_block}\n"
        f"{'=' * 60}\n"
        f"COMPETITOR INSIGHTS (gap opportunities)\n"
        f"{'=' * 60}\n"
        f"{competitor_block}\n"
        f"{'=' * 60}\n"
        f"TREND EVIDENCE ({len(top_results)} sources)\n"
        f"{'=' * 60}\n"
        f"{evidence_block}\n"
        f"{'=' * 60}\n"
        f"CTA BANK REFERENCE\n"
        f"{'=' * 60}\n"
        f"{cta_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Generate {MIN_CAMPAIGNS}–{MAX_CAMPAIGNS} standalone campaign "
        f"concepts for {brand_name}.\n"
        f"{'Generate the anniversary campaign — next anniversary is ' + next_ann_str if within_window else 'Set anniversary_campaign to null — anniversary is outside the window.'}\n"
        f"Every campaign must cite evidence from the sources above.\n"
        f"No campaign may duplicate any existing calendar topic.\n"
        f"All platforms must be from: {', '.join(social_platforms)}.\n"
        f"Return ONLY the JSON object — no markdown, no preamble, "
        f"no commentary."
    )

    return message


# ---------------------------------------------------------------------------
# LLM call and parser
# ---------------------------------------------------------------------------

async def _call_llm_and_parse(
    human_message: str,
    llm: ChatGroq,
    brand_name: str,
) -> dict[str, Any]:
    """
    Calls ChatGroq and parses the campaign JSON response.

    Parameters
    ----------
    human_message : str
        Campaign brief from _build_human_message.
    llm : ChatGroq
        Authenticated ChatGroq instance.
    brand_name : str
        Used for log context.

    Returns
    -------
    dict[str, Any]
        Parsed campaign output or error-flagged dict on failure.
    """
    messages = [
        SystemMessage(content=CAMPAIGN_SYSTEM_PROMPT),
        HumanMessage(content=human_message),
    ]

    logger.debug(
        "[%s] Invoking LLM | model=%s | brand='%s'",
        NODE_NAME,
        GROQ_MODEL,
        brand_name,
    )

    response = await llm.ainvoke(messages)
    raw_content: str = response.content

    if not raw_content or not raw_content.strip():
        logger.error(
            "[%s] LLM returned empty response | brand='%s'",
            NODE_NAME,
            brand_name,
        )
        return {"_parse_error": "LLM returned an empty response."}

    cleaned = raw_content.strip()

    # Strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        cleaned = "\n".join(lines).strip()

    try:
        parsed: dict[str, Any] = json.loads(cleaned)
        logger.debug(
            "[%s] LLM response parsed | brand='%s' | keys=%s",
            NODE_NAME,
            brand_name,
            list(parsed.keys()),
        )
        return parsed

    except json.JSONDecodeError as exc:
        logger.error(
            "[%s] JSON parse failure | brand='%s' | "
            "error=%s | preview='%s'",
            NODE_NAME,
            brand_name,
            str(exc),
            cleaned[:300],
        )
        return {
            "_parse_error": f"JSON decode failed: {str(exc)}",
            "_raw_response": cleaned[:500],
        }


# ---------------------------------------------------------------------------
# Campaign idea validator
# ---------------------------------------------------------------------------

def _validate_campaign_idea(
    raw: dict[str, Any],
    idx: int,
    social_platforms: set[str],
    brand_name: str,
    validation_errors: list[str],
) -> CampaignIdea | None:
    """
    Validates a single campaign idea dict and converts it to a
    typed CampaignIdea.

    Checks:
      1. Required fields present and non-empty.
      2. Platforms only reference valid social_platforms.
      3. content_arc is a non-empty list.
      4. evidence_sources is non-empty.
      5. duration_days is a positive integer.

    Parameters
    ----------
    raw : dict
        Raw campaign idea from LLM output.
    idx : int
        Campaign index for error messages.
    social_platforms : set[str]
        Valid platform names.
    brand_name : str
        Used for log context.
    validation_errors : list[str]
        Mutable list — errors appended here.

    Returns
    -------
    CampaignIdea | None
        Typed CampaignIdea if valid, None if critically malformed.
    """
    if not isinstance(raw, dict):
        validation_errors.append(
            f"Campaign {idx}: not a dict — skipped."
        )
        return None

    campaign_name = raw.get("name", f"Campaign {idx}")

    # ── Required field checks ─────────────────────────────────────────────
    missing_fields = [
        f for f in CAMPAIGN_IDEA_REQUIRED_FIELDS
        if not raw.get(f)
    ]
    for field in missing_fields:
        validation_errors.append(
            f"Campaign '{campaign_name}': missing field '{field}'."
        )

    # Critical fields — skip if absent
    if "name" not in raw or "core_message" not in raw:
        validation_errors.append(
            f"Campaign {idx}: missing critical fields "
            f"'name' or 'core_message' — skipped."
        )
        return None

    # ── Platform validation ───────────────────────────────────────────────
    raw_platforms = raw.get("platforms", [])
    if isinstance(raw_platforms, list):
        valid_plats = [p for p in raw_platforms if p in social_platforms]
        invalid_plats = [p for p in raw_platforms if p not in social_platforms]
        if invalid_plats:
            validation_errors.append(
                f"Campaign '{campaign_name}': removed invalid platforms "
                f"{invalid_plats}."
            )
    else:
        valid_plats = list(social_platforms)

    # ── Content arc validation ────────────────────────────────────────────
    content_arc = raw.get("content_arc", [])
    if not isinstance(content_arc, list) or len(content_arc) == 0:
        validation_errors.append(
            f"Campaign '{campaign_name}': content_arc is empty or missing."
        )
        content_arc = []

    # ── Evidence sources validation ───────────────────────────────────────
    evidence_sources = raw.get("evidence_sources", [])
    if not isinstance(evidence_sources, list) or len(evidence_sources) == 0:
        validation_errors.append(
            f"Campaign '{campaign_name}': evidence_sources is empty."
        )
        evidence_sources = []

    # ── duration_days validation ──────────────────────────────────────────
    try:
        duration_days = int(raw.get("duration_days", 7))
        if duration_days < 1:
            duration_days = 7
    except (ValueError, TypeError):
        duration_days = 7
        validation_errors.append(
            f"Campaign '{campaign_name}': invalid duration_days — "
            f"defaulting to 7."
        )

    # ── KPIs validation ───────────────────────────────────────────────────
    kpis = raw.get("kpis", [])
    if not isinstance(kpis, list) or len(kpis) == 0:
        validation_errors.append(
            f"Campaign '{campaign_name}': kpis is empty."
        )
        kpis = []

    return CampaignIdea(
        name=raw.get("name", f"Campaign {idx}"),
        objective=raw.get("objective", ""),
        duration_days=duration_days,
        platforms=valid_plats,
        core_message=raw.get("core_message", ""),
        content_formats=raw.get("content_formats", []),
        hook=raw.get("hook", ""),
        cta=raw.get("cta", ""),
        kpis=kpis,
        evidence_sources=evidence_sources,
    )


# ---------------------------------------------------------------------------
# Anniversary campaign validator
# ---------------------------------------------------------------------------

def _validate_anniversary_campaign(
    raw: Any,
    anniversary_context: dict[str, Any],
    social_platforms: set[str],
    brand_name: str,
    validation_errors: list[str],
) -> AnniversaryCampaign | None:
    """
    Validates the anniversary campaign object from the LLM response.

    Returns None if:
      - within_window is False (anniversary not in window)
      - raw is None or null
      - raw is missing critical fields

    Parameters
    ----------
    raw : Any
        Raw anniversary campaign from LLM output.
    anniversary_context : dict
        Computed anniversary metadata from _compute_anniversary_context.
    social_platforms : set[str]
        Valid platform names.
    brand_name : str
        Used for log context.
    validation_errors : list[str]
        Mutable list — errors appended here.

    Returns
    -------
    AnniversaryCampaign | None
    """
    # Not in window — should be null
    if not anniversary_context.get("within_window", False):
        if raw is not None:
            validation_errors.append(
                "anniversary_campaign: generated despite being outside "
                "the window. Discarding."
            )
        return None

    # In window but LLM returned null
    if raw is None:
        validation_errors.append(
            "anniversary_campaign: anniversary is within window but "
            "LLM returned null."
        )
        return None

    if not isinstance(raw, dict):
        validation_errors.append(
            "anniversary_campaign: not a dict — skipped."
        )
        return None

    # ── Required field checks ─────────────────────────────────────────────
    missing_fields = [
        f for f in ANNIVERSARY_REQUIRED_FIELDS
        if not raw.get(f)
    ]
    for field in missing_fields:
        validation_errors.append(
            f"anniversary_campaign: missing field '{field}'."
        )

    # ── Platform validation ───────────────────────────────────────────────
    raw_platforms = raw.get("platforms", [])
    if isinstance(raw_platforms, list):
        valid_plats = [p for p in raw_platforms if p in social_platforms]
        invalid_plats = [p for p in raw_platforms if p not in social_platforms]
        if invalid_plats:
            validation_errors.append(
                f"anniversary_campaign: removed invalid platforms "
                f"{invalid_plats}."
            )
    else:
        valid_plats = list(social_platforms)

    # ── year_milestone validation ─────────────────────────────────────────
    try:
        year_milestone = int(
            raw.get(
                "year_milestone",
                anniversary_context.get("next_anniversary_year", 1),
            )
        )
    except (ValueError, TypeError):
        year_milestone = anniversary_context.get(
            "next_anniversary_year", 1
        )

    # ── anniversary_date override with computed date ──────────────────────
    # Always use the computed date — do not trust the LLM's date arithmetic
    computed_date = anniversary_context.get("next_anniversary_date")
    anniversary_date_str = (
        computed_date.isoformat()
        if isinstance(computed_date, date)
        else raw.get("anniversary_date", "")
    )

    return AnniversaryCampaign(
        year_milestone=year_milestone,
        anniversary_date=anniversary_date_str,
        campaign_name=raw.get("campaign_name", "Anniversary Campaign"),
        theme=raw.get("theme", ""),
        key_message=raw.get("key_message", ""),
        content_arc=raw.get("content_arc", []),
        content_pieces=raw.get("content_pieces", []),
        platforms=valid_plats,
        hashtag=raw.get("hashtag", ""),
        cta=raw.get("cta", ""),
        community_activation=raw.get("community_activation", ""),
        evidence_sources=raw.get("evidence_sources", []),
    )


# ---------------------------------------------------------------------------
# Evidence audit extractor
# ---------------------------------------------------------------------------

def _extract_campaign_evidence(
    campaign_ideas: list[CampaignIdea],
    anniversary_campaign: AnniversaryCampaign | None,
) -> list[str]:
    """
    Collects and deduplicates all evidence sources cited across all
    campaign ideas and the anniversary campaign.

    Parameters
    ----------
    campaign_ideas : list[CampaignIdea]
        Validated campaign ideas.
    anniversary_campaign : AnniversaryCampaign | None
        Validated anniversary campaign or None.

    Returns
    -------
    list[str]
        Deduplicated list of evidence source strings.
    """
    seen: set[str] = set()
    sources: list[str] = []

    all_sources: list[str] = []
    for campaign in campaign_ideas:
        all_sources.extend(campaign.get("evidence_sources", []))

    if anniversary_campaign:
        all_sources.extend(
            anniversary_campaign.get("evidence_sources", [])
        )

    for source in all_sources:
        if source and isinstance(source, str) and source not in seen:
            seen.add(source)
            sources.append(source)

    return sources


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def campaign_generator_node(state: ContentState) -> dict[str, Any]:
    """
    Campaign Generator Node — LangGraph node entry point.

    Executes the full campaign generation pipeline:
      1. Extract inputs from state.
      2. Compute anniversary context from foundation_date.
      3. Build comprehensive campaign brief.
      4. Call LLM and parse response.
      5. Validate campaign ideas and anniversary campaign.
      6. Extract campaign_evidence_used audit trail.
      7. Finalise generation_metadata.
      8. Return state updates.

    Parameters
    ----------
    state : ContentState
        Current graph state.

    Returns
    -------
    dict[str, Any]
        Partial ContentState update merged by LangGraph.

    Notes
    -----
    - Never raises. All exceptions written to errors.
    - This is the terminal node — always routes to END.
    - Failure here does not affect generated_posts — the calendar
      is already complete in state.
    """
    start_time = time.monotonic()

    # ----------------------------------------------------------------
    # Extract inputs from state
    # ----------------------------------------------------------------
    brand_name: str = state.get("brand_name", "")
    industry: str = state.get("industry", "")
    country: str = state.get("country", "")
    city: str = state.get("city", "")
    foundation_date: str = state.get("foundation_date", "")
    social_platforms: list[str] = list(state.get("social_platforms") or [])
    brand_profile: dict[str, Any] | None = state.get("brand_profile")
    content_strategy: dict[str, Any] = dict(
        state.get("content_strategy") or {}
    )
    content_pillars: list[dict[str, Any]] = list(
        state.get("content_pillars") or []
    )
    trend_research_results: list[dict[str, Any]] = list(
        state.get("trend_research_results") or []
    )
    trending_topics: list[str] = list(state.get("trending_topics") or [])
    local_trends: list[str] = list(state.get("local_trends") or [])
    competitor_insights: list[dict[str, str]] = list(
        state.get("competitor_insights") or []
    )
    generated_posts: list[PostEntry] = list(
        state.get("generated_posts") or []
    )
    cta_bank: list[str] = list(state.get("cta_bank") or [])
    generation_metadata: dict[str, Any] = dict(
        state.get("generation_metadata") or {}
    )
    existing_errors: list[dict[str, str]] = list(state.get("errors") or [])
    existing_log: list[dict[str, Any]] = list(
        state.get("node_execution_log") or []
    )

    run_id: str = generation_metadata.get("run_id", "unknown")

    logger.info(
        "[%s] Starting | run_id=%s | brand='%s' | "
        "foundation='%s' | platforms=%s",
        NODE_NAME,
        run_id,
        brand_name,
        foundation_date,
        social_platforms,
    )

    # ----------------------------------------------------------------
    # Initialise output accumulators
    # ----------------------------------------------------------------
    campaign_ideas: list[CampaignIdea] = []
    anniversary_campaign: AnniversaryCampaign | None = None
    campaign_evidence_used: list[str] = []
    node_errors: list[dict[str, str]] = []
    validation_errors: list[str] = []
    execution_status: str = "success"
    anniversary_context: dict = {"within_window": False, "brand_age_years": 0}

    valid_platforms: set[str] = set(social_platforms)

    try:
        # ------------------------------------------------------------
        # Step 1: Compute anniversary context
        # ------------------------------------------------------------
        anniversary_context = _compute_anniversary_context(
            foundation_date_str=foundation_date,
            brand_name=brand_name,
        )

        logger.info(
            "[%s] Anniversary context | brand='%s' | "
            "within_window=%s | next=%s | milestone=%s",
            NODE_NAME,
            brand_name,
            anniversary_context.get("within_window"),
            anniversary_context.get("next_anniversary_date"),
            anniversary_context.get("is_milestone_year"),
        )

        # ------------------------------------------------------------
        # Step 2: Initialise LLM client
        # ------------------------------------------------------------
        llm = _get_llm()

        # ------------------------------------------------------------
        # Step 3: Build campaign brief
        # ------------------------------------------------------------
        human_message = _build_human_message(
            brand_name=brand_name,
            industry=industry,
            country=country,
            city=city,
            social_platforms=social_platforms,
            foundation_date=foundation_date,
            anniversary_context=anniversary_context,
            brand_profile=brand_profile,
            content_strategy=content_strategy,
            content_pillars=content_pillars,
            trend_research_results=trend_research_results,
            trending_topics=trending_topics,
            local_trends=local_trends,
            competitor_insights=competitor_insights,
            generated_posts=generated_posts,
            cta_bank=cta_bank,
        )

        # ------------------------------------------------------------
        # Step 4: Call LLM and parse
        # ------------------------------------------------------------
        parsed_output = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
        )

        if "_parse_error" in parsed_output:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": parsed_output["_parse_error"],
                    "field": "campaign_ideas",
                }
            )
            execution_status = "failed"
            raise RuntimeError("LLM parse failure in campaign node.")

        # ------------------------------------------------------------
        # Step 5a: Validate campaign ideas
        # ------------------------------------------------------------
        raw_campaigns = parsed_output.get("campaign_ideas", [])
        if not isinstance(raw_campaigns, list):
            raw_campaigns = []

        for idx, raw_campaign in enumerate(raw_campaigns, start=1):
            validated = _validate_campaign_idea(
                raw=raw_campaign,
                idx=idx,
                social_platforms=valid_platforms,
                brand_name=brand_name,
                validation_errors=validation_errors,
            )
            if validated is not None:
                campaign_ideas.append(validated)

        # Campaign count validation
        if len(campaign_ideas) < MIN_CAMPAIGNS:
            validation_errors.append(
                f"Only {len(campaign_ideas)} valid campaigns produced. "
                f"Minimum is {MIN_CAMPAIGNS}."
            )
            execution_status = "partial"

        if len(campaign_ideas) > MAX_CAMPAIGNS:
            validation_errors.append(
                f"Truncating {len(campaign_ideas)} campaigns to "
                f"{MAX_CAMPAIGNS}."
            )
            campaign_ideas = campaign_ideas[:MAX_CAMPAIGNS]

        # ------------------------------------------------------------
        # Step 5b: Validate anniversary campaign
        # ------------------------------------------------------------
        raw_anniversary = parsed_output.get("anniversary_campaign")
        anniversary_campaign = _validate_anniversary_campaign(
            raw=raw_anniversary,
            anniversary_context=anniversary_context,
            social_platforms=valid_platforms,
            brand_name=brand_name,
            validation_errors=validation_errors,
        )

        # Record all validation errors
        for ve in validation_errors:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": ve,
                    "field": "campaign_validation",
                }
            )
        if validation_errors:
            execution_status = "partial"

        # ------------------------------------------------------------
        # Step 6: Extract evidence audit trail
        # ------------------------------------------------------------
        campaign_evidence_used = _extract_campaign_evidence(
            campaign_ideas=campaign_ideas,
            anniversary_campaign=anniversary_campaign,
        )

        # ------------------------------------------------------------
        # Step 7: Finalise generation_metadata
        # ------------------------------------------------------------
        total_evidence = generation_metadata.get(
            "total_evidence_sources", 0
        ) + len(campaign_evidence_used)
        generation_metadata["total_evidence_sources"] = total_evidence

        logger.info(
            "[%s] Campaign generation complete | brand='%s' | "
            "campaigns=%d | anniversary=%s | evidence=%d | status=%s",
            NODE_NAME,
            brand_name,
            len(campaign_ideas),
            "YES" if anniversary_campaign else "NO",
            len(campaign_evidence_used),
            execution_status,
        )

    except RuntimeError:
        execution_status = "failed"

    except EnvironmentError as exc:
        logger.error(
            "[%s] Environment error | brand='%s' | error=%s",
            NODE_NAME,
            brand_name,
            str(exc),
        )
        node_errors.append(
            {
                "node": NODE_NAME,
                "message": str(exc),
                "field": "configuration",
            }
        )
        execution_status = "failed"

    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[%s] Unexpected error | brand='%s' | error=%s",
            NODE_NAME,
            brand_name,
            str(exc),
        )
        node_errors.append(
            {
                "node": NODE_NAME,
                "message": f"Unexpected error: {str(exc)}",
                "field": "campaign_generator_node",
            }
        )
        execution_status = "failed"

    # ----------------------------------------------------------------
    # Build execution log entry
    # ----------------------------------------------------------------
    duration_ms = int((time.monotonic() - start_time) * 1000)

    log_entry: dict[str, Any] = {
        "node": NODE_NAME,
        "status": execution_status,
        "evidence_count": len(campaign_evidence_used),
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[%s] Complete | run_id=%s | brand='%s' | status=%s | "
        "campaigns=%d | anniversary=%s | errors=%d | duration_ms=%d",
        NODE_NAME,
        run_id,
        brand_name,
        execution_status,
        len(campaign_ideas),
        "YES" if anniversary_campaign else "NO",
        len(node_errors),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # ----------------------------------------------------------------
    return {
        "campaign_ideas": campaign_ideas if campaign_ideas else [],
        "anniversary_campaign": anniversary_campaign,
        "campaign_evidence_used": campaign_evidence_used,
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }