from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from calendar_prompt import (
    CALENDAR_SYSTEM_PROMPT,
    VALID_CONTENT_TYPES,
    VALID_DAYS_OF_WEEK,
)
from content_state import ContentPillar, ContentState, PostEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "calendar_builder_node"

GROQ_COOLDOWN_SECONDS: float = float(os.getenv("GROQ_COOLDOWN_SECONDS", "5"))

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Higher token budget — the calendar is a large JSON array
LLM_TEMPERATURE: float = 0.2
LLM_MAX_TOKENS: int = 4096

# Distribution audit tolerances
DISTRIBUTION_TOLERANCE: int = 2

# Maximum percentage of total posts any single week may contain
MAX_WEEK_PERCENTAGE: float = 0.40

# Minimum percentage of total posts any single week must contain
MIN_WEEK_PERCENTAGE: float = 0.10

# Maximum number of trend results to surface in the scheduling brief
MAX_TREND_RESULTS_IN_PROMPT: int = 5

# Platform → valid content types mapping for format-alignment validation
PLATFORM_FORMAT_MAP: dict[str, frozenset[str]] = {
    "Instagram": frozenset({"Reel", "Carousel", "Static", "Story"}),
    "TikTok": frozenset({"Reel", "Short Video"}),
    "LinkedIn": frozenset({"Carousel", "Static", "Infographic", "Poll", "Thread"}),
    "X": frozenset({"Static", "Thread", "Poll", "Quote Card"}),
    "Facebook": frozenset({"Static", "Reel", "Carousel", "Poll", "Behind the Scenes"}),
    "Pinterest": frozenset({"Static", "Infographic", "Carousel"}),
    "Threads": frozenset({"Static", "Thread", "Quote Card"}),
    "YouTube Shorts": frozenset({"Short Video", "Reel"}),
}

# Aliases: LLM-invented names → canonical VALID_CONTENT_TYPES names
# Applied BEFORE platform-format validation so one correction is enough.
CONTENT_TYPE_ALIASES: dict[str, str] = {
    "short reel":      "Reel",
    "Short-form video": "Reel",
    "Short video":      "Reel",
    "Feed post":        "Static",   
    "Image post":       "Static",
    "Single image":     "Static",
    "Photo post":       "Static",
    "Link post":        "Static",
    "video":            "Reel",
    "video post":       "Reel",
    "feed post":        "Static",
    "image":            "Static",
    "photo":            "Static",
    "link post":        "Static",
    "text post":        "Static",
    "feed":             "Static",
}

# Preferred fallback type per platform when the resolved type is still invalid.
# Used by the diversifier and the per-slot validator.
PLATFORM_FALLBACK_TYPES: dict[str, list[str]] = {
    "Instagram":     ["Reel", "Carousel", "Static", "Story"],
    "TikTok":        ["Reel", "Short Video"],
    "LinkedIn":      ["Carousel", "Static", "Infographic", "Poll", "Thread"],
    "X":             ["Static", "Thread", "Poll", "Quote Card"],
    "Facebook":      ["Static", "Reel", "Carousel", "Poll", "Behind the Scenes"],
    "Pinterest":     ["Static", "Infographic", "Carousel"],
    "Threads":       ["Static", "Thread", "Quote Card"],
    "YouTube Shorts":["Short Video", "Reel"],
}


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY2")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY2 environment variable is not set. "
            "Calendar builder node cannot call the LLM without it."
        )
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Human message builder
# ---------------------------------------------------------------------------

def _build_human_message(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    social_platforms: list[str],
    posts_per_month: int,
    content_strategy: dict[str, Any],
    content_pillars: list[ContentPillar],
    trending_topics: list[str],
    local_trends: list[str],
    trend_research_results: list[dict[str, Any]],
) -> str:
    """
    Constructs the scheduling brief passed to the LLM.

    Sections:
      - Brand parameters
      - Platform posting frequencies from strategy
      - Content pillar allocations with percentages
      - Tone guidelines summary
      - Trending topics and local events
      - Top evidence sources for topic grounding

    Parameters
    ----------
    brand_name, industry, country, city : str
        Core brand parameters.
    social_platforms : list[str]
        Platforms to schedule across.
    posts_per_month : int
        Exact number of post slots to generate.
    content_strategy : dict
        Full strategy document from content_strategy_node.
    content_pillars : list[ContentPillar]
        Validated pillars with names and percentages.
    trending_topics : list[str]
        Flat topic labels from trend research.
    local_trends : list[str]
        City/country-specific signals and events.
    trend_research_results : list[dict]
        Master evidence list for topic citation.

    Returns
    -------
    str
        Fully formatted scheduling brief.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Platform frequency block ──────────────────────────────────────────
    posting_frequency: dict[str, Any] = content_strategy.get(
        "posting_frequency", {}
    )
    platform_lines: list[str] = []
    for platform in social_platforms:
        freq_data = posting_frequency.get(platform, {})
        if freq_data:
            posts_per_week = freq_data.get("posts_per_week", "N/A")
            best_days = freq_data.get("best_days", [])
            best_times = freq_data.get("best_times", "N/A")
            platform_lines.append(
                f"  {platform}:\n"
                f"    Posts/Week : {posts_per_week}\n"
                f"    Best Days  : {', '.join(best_days) if best_days else 'N/A'}\n"
                f"    Best Times : {best_times}"
            )
        else:
            platform_lines.append(
                f"  {platform}:\n"
                f"    Posts/Week : Not specified in strategy\n"
                f"    Best Days  : Distribute evenly\n"
                f"    Best Times : N/A"
            )
    platform_block = "\n".join(platform_lines)

    # ── Pillar allocation block ───────────────────────────────────────────
    pillar_lines: list[str] = []
    for pillar in content_pillars:
        pillar_name = pillar.get("name", "Unknown")
        pillar_pct = pillar.get("percentage", 0)
        pillar_posts = round(posts_per_month * pillar_pct / 100)
        post_types = pillar.get("post_types", [])
        evidence = pillar.get("evidence", [])
        pillar_lines.append(
            f"  • {pillar_name} ({pillar_pct}% → ~{pillar_posts} posts)\n"
            f"    Formats   : {', '.join(post_types) if post_types else 'Any'}\n"
            f"    Evidence  : {evidence[0] if evidence else 'N/A'}"
        )
    pillar_block = "\n".join(pillar_lines)

    # ── Platform strategy summary ─────────────────────────────────────────
    platform_strategy: dict[str, Any] = content_strategy.get(
        "platform_strategy", {}
    )
    strategy_lines: list[str] = []
    for platform in social_platforms:
        ps = platform_strategy.get(platform, {})
        if ps:
            strategy_lines.append(
                f"  {platform}: {ps.get('content_focus', 'N/A')} | "
                f"Best formats: {', '.join(ps.get('best_formats', []))}"
            )
    strategy_block = (
        "\n".join(strategy_lines) if strategy_lines
        else "  No platform strategy details available."
    )

    # ── Tone summary ──────────────────────────────────────────────────────
    tone_guidelines: dict[str, Any] = content_strategy.get(
        "tone_guidelines", {}
    )
    tone_block = (
        f"  Voice    : {tone_guidelines.get('overall_voice', 'N/A')}\n"
        f"  Language : {tone_guidelines.get('language_style', 'N/A')}\n"
        f"  Culture  : {tone_guidelines.get('cultural_adaptations', 'N/A')}"
    )

    # ── Trending topics block ─────────────────────────────────────────────
    topics_block = (
        "\n".join(f"  • {t}" for t in trending_topics[:15])
        if trending_topics
        else "  No trending topics available."
    )

    # ── Local trends / events block ───────────────────────────────────────
    local_block = (
        "\n".join(f"  • {t}" for t in local_trends)
        if local_trends
        else "  No local events or trends available."
    )

    # ── Top evidence sources ──────────────────────────────────────────────
    # Prioritise synthesised findings with event/holiday relevance
    scored_results = sorted(
        [r for r in trend_research_results
         if r.get("type") == "raw_search_result"],
        key=lambda x: x.get("score", 0.0),
        reverse=True,
    )
    synthesised = [
        r for r in trend_research_results
        if r.get("type") == "synthesised_finding"
    ]
    top_results = (synthesised + scored_results)[:MAX_TREND_RESULTS_IN_PROMPT]

    evidence_lines: list[str] = []
    for i, r in enumerate(top_results, start=1):
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
            evidence_lines.append(
                f"  [{i}] [{r.get('category','').upper()}] {label}\n"
                f"       Source: {r.get('source', 'N/A')}"
            )
        else:
            evidence_lines.append(
                f"  [{i}] [{r.get('category','').upper()}] "
                f"{r.get('title', 'N/A')}\n"
                f"       Snippet: {r.get('snippet', 'N/A')[:80]}"
            )
    evidence_block = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "  No trend evidence available for topic grounding."
    )

    # ── Strategic goal ────────────────────────────────────────────────────
    strategic_goal = content_strategy.get(
        "strategic_goal",
        "Build brand presence across all platforms.",
    )

    message = (
        f"TODAY'S DATE: {today_str}\n"
        f"{'=' * 60}\n"
        f"SCHEDULING PARAMETERS\n"
        f"{'=' * 60}\n"
        f"  Brand Name      : {brand_name}\n"
        f"  Industry        : {industry}\n"
        f"  Country         : {country}\n"
        f"  City            : {city}\n"
        f"  Social Platforms: {', '.join(social_platforms)}\n"
        f"  Posts Per Month : {posts_per_month} (EXACT — no more, no fewer)\n"
        f"{'=' * 60}\n"
        f"STRATEGIC GOAL\n"
        f"{'=' * 60}\n"
        f"  {strategic_goal}\n"
        f"{'=' * 60}\n"
        f"PLATFORM POSTING FREQUENCIES\n"
        f"{'=' * 60}\n"
        f"{platform_block}\n"
        f"{'=' * 60}\n"
        f"CONTENT PILLARS & ALLOCATIONS\n"
        f"{'=' * 60}\n"
        f"{pillar_block}\n"
        f"{'=' * 60}\n"
        f"PLATFORM STRATEGY SUMMARY\n"
        f"{'=' * 60}\n"
        f"{strategy_block}\n"
        f"{'=' * 60}\n"
        f"TONE GUIDELINES\n"
        f"{'=' * 60}\n"
        f"{tone_block}\n"
        f"{'=' * 60}\n"
        f"TRENDING TOPICS (for topic grounding)\n"
        f"{'=' * 60}\n"
        f"{topics_block}\n"
        f"{'=' * 60}\n"
        f"LOCAL EVENTS & CULTURAL MOMENTS (for tie-ins)\n"
        f"{'=' * 60}\n"
        f"{local_block}\n"
        f"{'=' * 60}\n"
        f"TREND EVIDENCE (for evidence_sources citations)\n"
        f"{'=' * 60}\n"
        f"{evidence_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Build the complete monthly content calendar for {brand_name}.\n"
        f"Output a JSON array of exactly {posts_per_month} post slot objects.\n"
        f"Cover all platforms: {', '.join(social_platforms)}.\n"
        f"Distribute posts proportionally to pillar percentages and "
        f"platform frequencies.\n"
        f"Tie in local events at the correct week positions.\n"
        f"Every topic must be specific and publishable.\n"
        f"Return ONLY the JSON array — no markdown, no preamble, "
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
) -> list[dict[str, Any]]:
    """
    Calls ChatGroq and parses the JSON array calendar response.

    Parameters
    ----------
    human_message : str
        Scheduling brief from _build_human_message.
    llm : ChatGroq
        Authenticated ChatGroq instance.
    brand_name : str
        Used for log context.

    Returns
    -------
    list[dict[str, Any]]
        Parsed list of raw post slot dicts.
        Returns empty list on parse failure.
    """
    messages = [
        SystemMessage(content=CALENDAR_SYSTEM_PROMPT),
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
        return []

    cleaned = raw_content.strip()

    # Strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        cleaned = "\n".join(lines).strip()

    # Handle wrapped object e.g. {"calendar": [...]}
    if cleaned.startswith("{"):
        try:
            wrapper = json.loads(cleaned)
            for key in ("calendar", "posts", "content_calendar", "items"):
                if key in wrapper and isinstance(wrapper[key], list):
                    cleaned = json.dumps(wrapper[key])
                    break
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            logger.error(
                "[%s] Expected JSON array, got %s | brand='%s'",
                NODE_NAME,
                type(parsed).__name__,
                brand_name,
            )
            return []
        logger.debug(
            "[%s] Parsed %d post slots | brand='%s'",
            NODE_NAME,
            len(parsed),
            brand_name,
        )
        return parsed

    except json.JSONDecodeError as exc:
        logger.error(
            "[%s] JSON parse failure | brand='%s' | error=%s | preview='%s'",
            NODE_NAME,
            brand_name,
            str(exc),
            cleaned[:300],
        )
        return []


# ---------------------------------------------------------------------------
# Per-slot validator and normaliser
# ---------------------------------------------------------------------------

def _validate_and_build_post_entry(
    raw: dict[str, Any],
    post_number: int,
    valid_platforms: set[str],
    valid_pillar_names: set[str],
    slot_errors: list[str],
) -> PostEntry | None:
    """
    Validates a single raw post slot dict and converts it to a
    typed PostEntry.

    Validation checks:
      - Required fields present and non-empty
      - platform is in valid_platforms
      - content_pillar is in valid_pillar_names
      - content_type is in VALID_CONTENT_TYPES
      - day_of_week is in VALID_DAYS_OF_WEEK
      - week is 1–4
      - content_type is compatible with platform

    Normalisation:
      - Overrides post_number with the sequential counter
      - Ensures evidence_sources is a list
      - Sets reel_script to None (filled by content_generator_node)
      - Sets caption to empty string (filled by content_generator_node)
      - Sets hashtags to empty list (filled by content_generator_node)
      - Sets cta to empty string (filled by content_generator_node)

    Parameters
    ----------
    raw : dict
        Raw post slot from LLM output.
    post_number : int
        Sequential index (1-based) from the node, overrides LLM value.
    valid_platforms : set[str]
        Accepted platform names from social_platforms.
    valid_pillar_names : set[str]
        Accepted pillar names from content_pillars.
    slot_errors : list[str]
        Mutable list — validation errors appended here.

    Returns
    -------
    PostEntry | None
        Typed PostEntry if valid enough to include, None if critically
        malformed (missing platform or pillar).
    """
    if not isinstance(raw, dict):
        slot_errors.append(f"Slot {post_number}: not a dict — skipped.")
        return None

    # ── Required field presence ───────────────────────────────────────────
    platform: str = raw.get("platform", "")
    content_pillar: str = raw.get("content_pillar", "")
    content_type: str = raw.get("content_type", "Static")
    topic: str = raw.get("topic", "")
    day_of_week: str = raw.get("day_of_week", "Monday")
    week_raw = raw.get("week", 1)

    # Platform validation — critical: skip slot if invalid
    if not platform or platform not in valid_platforms:
        slot_errors.append(
            f"Slot {post_number}: invalid platform '{platform}'. "
            f"Valid: {sorted(valid_platforms)}. Slot skipped."
        )
        return None

    # Pillar validation — critical: skip slot if invalid
    if not content_pillar or content_pillar not in valid_pillar_names:
        # Attempt fuzzy match — assign to first pillar if only one char off
        matched = _fuzzy_match_pillar(content_pillar, valid_pillar_names)
        if matched:
            slot_errors.append(
                f"Slot {post_number}: pillar '{content_pillar}' "
                f"fuzzy-matched to '{matched}'."
            )
            content_pillar = matched
        else:
            slot_errors.append(
                f"Slot {post_number}: unknown pillar '{content_pillar}'. "
                f"Valid: {sorted(valid_pillar_names)}. Slot skipped."
            )
            return None

    # Step 1: Apply alias normalisation FIRST — resolve LLM-invented names
    # to canonical types in a single step before any other checks.
    alias_key = content_type.lower().strip()
    if alias_key in CONTENT_TYPE_ALIASES:
        resolved = CONTENT_TYPE_ALIASES[alias_key]
        slot_errors.append(
            f"Slot {post_number}: content_type '{content_type}' "
            f"normalised to '{resolved}' via alias map."
        )
        content_type = resolved

    # Step 2: Check canonical validity
    if content_type not in VALID_CONTENT_TYPES:
        # Last-resort: pick first valid type for this platform
        fallback = (PLATFORM_FALLBACK_TYPES.get(platform) or ["Static"])[0]
        slot_errors.append(
            f"Slot {post_number}: unknown content_type '{content_type}'. "
            f"Defaulting to '{fallback}'."
        )
        content_type = fallback

    # Step 3: Format-platform alignment
    valid_types_for_platform = PLATFORM_FORMAT_MAP.get(platform, frozenset())
    if valid_types_for_platform and content_type not in valid_types_for_platform:
        # Pick platform-appropriate fallback
        fallback = (PLATFORM_FALLBACK_TYPES.get(platform) or ["Static"])[0]
        slot_errors.append(
            f"Slot {post_number}: content_type '{content_type}' is not "
            f"valid for platform '{platform}'. Defaulting to '{fallback}'."
        )
        content_type = fallback

    # Day of week validation
    if day_of_week not in VALID_DAYS_OF_WEEK:
        slot_errors.append(
            f"Slot {post_number}: invalid day_of_week '{day_of_week}'. "
            f"Defaulting to 'Monday'."
        )
        day_of_week = "Monday"

    # Week validation
    try:
        week = int(week_raw)
        if week not in (1, 2, 3, 4):
            slot_errors.append(
                f"Slot {post_number}: week={week} out of range. "
                f"Clamping to 1–4."
            )
            week = max(1, min(4, week))
    except (ValueError, TypeError):
        slot_errors.append(
            f"Slot {post_number}: invalid week value '{week_raw}'. "
            f"Defaulting to 1."
        )
        week = 1

    # Topic non-empty check
    if not topic or not topic.strip():
        slot_errors.append(
            f"Slot {post_number}: empty topic — "
            f"placeholder inserted."
        )
        topic = f"[Topic needed for slot {post_number} — {platform} / {content_pillar}]"

    # Evidence sources normalisation
    raw_evidence = raw.get("evidence_sources", [])
    evidence_sources: list[str] = (
        raw_evidence if isinstance(raw_evidence, list) else []
    )

    # Build PostEntry — caption/hashtags/CTA/script left empty
    # for content_generator_node to fill
    return PostEntry(
        post_number=post_number,
        week=week,
        day_of_week=day_of_week,
        platform=platform,
        content_pillar=content_pillar,
        content_type=content_type,
        topic=topic,
        caption="",
        hashtags=[],
        cta="",
        reel_script=None,
        evidence_sources=evidence_sources,
    )


def _fuzzy_match_pillar(
    candidate: str,
    valid_names: set[str],
) -> str | None:
    """
    Attempts a simple case-insensitive prefix match for pillar names.
    Returns the matched name or None.
    """
    if not candidate:
        return None
    candidate_lower = candidate.lower().strip()
    for name in valid_names:
        if (
            name.lower().startswith(candidate_lower[:5])
            or candidate_lower.startswith(name.lower()[:5])
        ):
            return name
    return None



# ---------------------------------------------------------------------------
# Content type auto-diversifier
# ---------------------------------------------------------------------------

def _diversify_content_types(
    calendar: list[PostEntry],
    social_platforms: list[str],
) -> tuple[list[PostEntry], list[str]]:
    """Rotates over-represented content types to satisfy Rule 5 (max 50% per platform)."""
    from collections import Counter
    changes: list[str] = []

    for platform in social_platforms:
        platform_indices = [
            i for i, p in enumerate(calendar)
            if p.get("platform") == platform
        ]
        if len(platform_indices) < 2:
            continue

        available = PLATFORM_FALLBACK_TYPES.get(platform, ["Static", "Reel"])
        total = len(platform_indices)
        max_allowed = max(1, total // 2)

        type_counts = Counter(
            calendar[i].get("content_type", "Static") for i in platform_indices
        )

        for ct, count in type_counts.items():
            if count <= max_allowed:
                continue
            excess = count - max_allowed
            replaced = 0
            cycle = 0
            for i in platform_indices:
                if calendar[i].get("content_type") != ct:
                    continue
                if replaced >= excess:
                    break
                # find next candidate that differs
                candidate = ct
                for _ in range(len(available)):
                    candidate = available[cycle % len(available)]
                    cycle += 1
                    if candidate != ct:
                        break
                if candidate != ct:
                    old = calendar[i].get("content_type", ct)
                    calendar[i]["content_type"] = candidate
                    changes.append(
                        f"Post #{calendar[i].get('post_number')} [{platform}]: "
                        f"{old!r} rotated to {candidate!r} (Rule 5)"
                    )
                    replaced += 1

    return calendar, changes

# ---------------------------------------------------------------------------
# Distribution auditor
# ---------------------------------------------------------------------------

def _audit_distribution(
    calendar: list[PostEntry],
    social_platforms: list[str],
    content_pillars: list[ContentPillar],
    posts_per_month: int,
) -> list[str]:
    """
    Audits the validated calendar against the 8 distribution rules.

    Returns a list of violation descriptions. An empty list means
    the calendar passed all checks. Violations are non-fatal — they
    are written to state errors but do not halt the graph.

    Parameters
    ----------
    calendar : list[PostEntry]
        Validated calendar entries.
    social_platforms : list[str]
        Expected platforms.
    content_pillars : list[ContentPillar]
        Expected pillars with percentage targets.
    posts_per_month : int
        Expected total post count.

    Returns
    -------
    list[str]
        Distribution violation descriptions.
    """
    violations: list[str] = []
    total = len(calendar)

    # ── Rule 1: Post count ────────────────────────────────────────────────
    if total != posts_per_month:
        violations.append(
            f"Rule 1 — Post count: expected {posts_per_month}, "
            f"got {total}."
        )

    if total == 0:
        return violations  # No point auditing further

    # ── Rule 2: Platform distribution ────────────────────────────────────
    platform_counts: dict[str, int] = defaultdict(int)
    for post in calendar:
        platform_counts[post.get("platform", "")] += 1

    for platform in social_platforms:
        if platform_counts.get(platform, 0) == 0:
            violations.append(
                f"Rule 2 — Platform distribution: platform '{platform}' "
                f"has 0 posts."
            )

    # ── Rule 3: Pillar distribution ───────────────────────────────────────
    pillar_counts: dict[str, int] = defaultdict(int)
    for post in calendar:
        pillar_counts[post.get("content_pillar", "")] += 1

    for pillar in content_pillars:
        pillar_name = pillar.get("name", "")
        pillar_pct = pillar.get("percentage", 0)
        expected = round(total * pillar_pct / 100)
        actual = pillar_counts.get(pillar_name, 0)

        if actual == 0:
            violations.append(
                f"Rule 3 — Pillar distribution: pillar '{pillar_name}' "
                f"has 0 posts (expected ~{expected})."
            )
        elif abs(actual - expected) > DISTRIBUTION_TOLERANCE:
            violations.append(
                f"Rule 3 — Pillar distribution: pillar '{pillar_name}' "
                f"has {actual} posts, expected ~{expected} "
                f"({pillar_pct}% of {total})."
            )

    # ── Rule 4: Weekly spread ─────────────────────────────────────────────
    week_counts: dict[int, int] = defaultdict(int)
    for post in calendar:
        week_counts[post.get("week", 1)] += 1

    for week in (1, 2, 3, 4):
        count = week_counts.get(week, 0)
        week_pct = count / total if total > 0 else 0
        if week_pct > MAX_WEEK_PERCENTAGE:
            violations.append(
                f"Rule 4 — Weekly spread: week {week} has {count} posts "
                f"({week_pct:.0%}), exceeds {MAX_WEEK_PERCENTAGE:.0%} max."
            )
        elif total >= 8 and week_pct < MIN_WEEK_PERCENTAGE:
            violations.append(
                f"Rule 4 — Weekly spread: week {week} has {count} posts "
                f"({week_pct:.0%}), below {MIN_WEEK_PERCENTAGE:.0%} min."
            )

    # ── Rule 5: Content type variety per platform ─────────────────────────
    platform_types: dict[str, set[str]] = defaultdict(set)
    platform_type_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for post in calendar:
        plat = post.get("platform", "")
        ct = post.get("content_type", "")
        platform_types[plat].add(ct)
        platform_type_counts[plat][ct] += 1

    for platform, type_counts in platform_type_counts.items():
        plat_total = sum(type_counts.values())
        for ct, count in type_counts.items():
            if plat_total > 0 and count / plat_total > 0.5:
                violations.append(
                    f"Rule 5 — Content type variety: '{ct}' represents "
                    f"{count}/{plat_total} posts ({count/plat_total:.0%}) "
                    f"on {platform} — exceeds 50% threshold."
                )
        if len(platform_types[platform]) < 2:
            violations.append(
                f"Rule 5 — Content type variety: {platform} uses fewer "
                f"than 2 distinct content types."
            )

    # ── Rule 6: Topic uniqueness ──────────────────────────────────────────
    seen_topics: set[str] = set()
    for post in calendar:
        topic = post.get("topic", "").lower().strip()
        if topic and topic in seen_topics:
            violations.append(
                f"Rule 6 — Topic uniqueness: duplicate topic detected: "
                f"'{post.get('topic', '')}'"
            )
        seen_topics.add(topic)

    return violations


# ---------------------------------------------------------------------------
# Calendar summary builder
# ---------------------------------------------------------------------------

def _build_calendar_summary(
    calendar: list[PostEntry],
    posts_per_month: int,
) -> dict[str, Any]:
    """
    Builds aggregate statistics over the validated calendar for QA
    and observability.

    Parameters
    ----------
    calendar : list[PostEntry]
        Validated calendar entries.
    posts_per_month : int
        Originally requested post count.

    Returns
    -------
    dict[str, Any]
        Summary statistics matching the ContentState.calendar_summary shape.
    """
    posts_by_platform: dict[str, int] = defaultdict(int)
    posts_by_pillar: dict[str, int] = defaultdict(int)
    posts_by_type: dict[str, int] = defaultdict(int)
    posts_by_week: dict[int, int] = defaultdict(int)

    for post in calendar:
        posts_by_platform[post.get("platform", "Unknown")] += 1
        posts_by_pillar[post.get("content_pillar", "Unknown")] += 1
        posts_by_type[post.get("content_type", "Unknown")] += 1
        posts_by_week[post.get("week", 0)] += 1

    return {
        "total_posts": len(calendar),
        "posts_requested": posts_per_month,
        "posts_by_platform": dict(posts_by_platform),
        "posts_by_pillar": dict(posts_by_pillar),
        "posts_by_type": dict(posts_by_type),
        "posts_by_week": dict(posts_by_week),
        "weeks_covered": len(
            {post.get("week") for post in calendar if post.get("week")}
        ),
        "platforms_covered": len(
            {post.get("platform") for post in calendar if post.get("platform")}
        ),
    }


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def calendar_builder_node(state: ContentState) -> dict[str, Any]:
    """
    Calendar Builder Node — LangGraph node entry point.

    Executes the full calendar production pipeline:
      1. Extract inputs from state.
      2. Build scheduling brief from strategy + pillars + evidence.
      3. Call LLM and parse JSON array response.
      4. Validate and normalise each post slot.
      5. Audit distribution rules.
      6. Build calendar_summary.
      7. Return state updates.

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
    - content_calendar will be empty on total failure, halting the graph.
    - Distribution violations are non-fatal — written to errors but
      the calendar is still returned.
    """
    # Rate-limit cooldown — prevents Groq free-tier 429s
    # when nodes fire back-to-back. Set GROQ_COOLDOWN_SECONDS=0
    # on paid Groq tier.
    if GROQ_COOLDOWN_SECONDS > 0:
        import logging as _log
        _log.getLogger(__name__).info(
            "[calendar_builder_node] Rate-limit cooldown | sleeping=%.1fs",
            GROQ_COOLDOWN_SECONDS,
        )
        await asyncio.sleep(GROQ_COOLDOWN_SECONDS)

    start_time = time.monotonic()

    # ----------------------------------------------------------------
    # Extract inputs from state
    # ----------------------------------------------------------------
    brand_name: str = state.get("brand_name", "")
    industry: str = state.get("industry", "")
    country: str = state.get("country", "")
    city: str = state.get("city", "")
    social_platforms: list[str] = list(state.get("social_platforms") or [])
    posts_per_month: int = int(state.get("posts_per_month") or 0)
    content_strategy: dict[str, Any] = dict(
        state.get("content_strategy") or {}
    )
    content_pillars: list[ContentPillar] = list(
        state.get("content_pillars") or []
    )
    trending_topics: list[str] = list(state.get("trending_topics") or [])
    local_trends: list[str] = list(state.get("local_trends") or [])
    trend_research_results: list[dict[str, Any]] = list(
        state.get("trend_research_results") or []
    )
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
        "platforms=%s | posts=%d | pillars=%d",
        NODE_NAME,
        run_id,
        brand_name,
        social_platforms,
        posts_per_month,
        len(content_pillars),
    )

    # ----------------------------------------------------------------
    # Initialise output accumulators
    # ----------------------------------------------------------------
    content_calendar: list[PostEntry] = []
    calendar_summary: dict[str, Any] = {}
    node_errors: list[dict[str, str]] = []
    execution_status: str = "success"

    # Precompute valid name sets for slot validation
    valid_platforms: set[str] = set(social_platforms)
    valid_pillar_names: set[str] = {
        p.get("name", "") for p in content_pillars if p.get("name")
    }

    try:
        # ------------------------------------------------------------
        # Step 1: Initialise LLM client
        # ------------------------------------------------------------
        llm = _get_llm()

        # ------------------------------------------------------------
        # Step 2: Build scheduling brief
        # ------------------------------------------------------------
        human_message = _build_human_message(
            brand_name=brand_name,
            industry=industry,
            country=country,
            city=city,
            social_platforms=social_platforms,
            posts_per_month=posts_per_month,
            content_strategy=content_strategy,
            content_pillars=content_pillars,
            trending_topics=trending_topics,
            local_trends=local_trends,
            trend_research_results=trend_research_results,
        )

        # ------------------------------------------------------------
        # Step 3: Call LLM and parse
        # ------------------------------------------------------------
        raw_slots = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
        )

        if not raw_slots:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": "LLM returned no calendar slots.",
                    "field": "content_calendar",
                }
            )
            execution_status = "failed"
            # Return early — no point continuing without slots
            raise RuntimeError("LLM returned no calendar slots.")

        logger.info(
            "[%s] LLM returned %d raw slots | brand='%s'",
            NODE_NAME,
            len(raw_slots),
            brand_name,
        )

        # ------------------------------------------------------------
        # Step 4: Validate and normalise each slot
        # ------------------------------------------------------------
        slot_errors: list[str] = []
        for idx, raw in enumerate(raw_slots):
            entry = _validate_and_build_post_entry(
                raw=raw,
                post_number=idx + 1,
                valid_platforms=valid_platforms,
                valid_pillar_names=valid_pillar_names,
                slot_errors=slot_errors,
            )
            if entry is not None:
                content_calendar.append(entry)

        # Record slot-level errors
        for se in slot_errors:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": se,
                    "field": "content_calendar_slot",
                }
            )
        if slot_errors:
            execution_status = "partial"

        logger.info(
            "[%s] Slot validation complete | brand='%s' | "
            "valid=%d | skipped=%d",
            NODE_NAME,
            brand_name,
            len(content_calendar),
            len(raw_slots) - len(content_calendar),
        )

        # ------------------------------------------------------------
        # Step 4b: Auto-diversify content types (Rule 5 enforcement)
        # Rotates over-represented types before the audit runs so
        # violations are fixed silently rather than just flagged.
        # ------------------------------------------------------------
        if content_calendar:
            content_calendar, diversity_changes = _diversify_content_types(
                calendar=content_calendar,
                social_platforms=social_platforms,
            )
            for change in diversity_changes:
                logger.info(
                    "[%s] Auto-diversified | brand='%s' | %s",
                    NODE_NAME, brand_name, change,
                )

        # ------------------------------------------------------------
        # Step 5: Distribution audit
        # ------------------------------------------------------------
        if content_calendar:
            violations = _audit_distribution(
                calendar=content_calendar,
                social_platforms=social_platforms,
                content_pillars=content_pillars,
                posts_per_month=posts_per_month,
            )
            for v in violations:
                node_errors.append(
                    {
                        "node": NODE_NAME,
                        "message": v,
                        "field": "calendar_distribution",
                    }
                )
            if violations:
                execution_status = "partial"
                logger.warning(
                    "[%s] Distribution audit found %d violation(s) | "
                    "brand='%s'",
                    NODE_NAME,
                    len(violations),
                    brand_name,
                )
            else:
                logger.info(
                    "[%s] Distribution audit passed | brand='%s'",
                    NODE_NAME,
                    brand_name,
                )

        # ------------------------------------------------------------
        # Step 6: Build calendar summary
        # ------------------------------------------------------------
        calendar_summary = _build_calendar_summary(
            calendar=content_calendar,
            posts_per_month=posts_per_month,
        )

        logger.info(
            "[%s] Calendar built | brand='%s' | posts=%d | "
            "platforms=%s | weeks=%d",
            NODE_NAME,
            brand_name,
            len(content_calendar),
            list(calendar_summary.get("posts_by_platform", {}).keys()),
            calendar_summary.get("weeks_covered", 0),
        )

    except RuntimeError:
        # Already recorded in node_errors above — just set status
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
                "field": "calendar_builder_node",
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
        "evidence_count": len(content_calendar),
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[%s] Complete | run_id=%s | brand='%s' | status=%s | "
        "posts=%d | errors=%d | duration_ms=%d",
        NODE_NAME,
        run_id,
        brand_name,
        execution_status,
        len(content_calendar),
        len(node_errors),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # ----------------------------------------------------------------
    return {
        "content_calendar": content_calendar if content_calendar else [],
        "calendar_summary": calendar_summary if calendar_summary else {},
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }