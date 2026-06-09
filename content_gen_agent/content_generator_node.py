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

from content_generation_prompt import (
    CONTENT_GENERATION_SYSTEM_PROMPT,
    PLATFORM_CAPTION_RULES,
)
from content_state import ContentPillar, ContentState, PostEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "content_generator_node"

GROQ_COOLDOWN_SECONDS: float = float(os.getenv("GROQ_COOLDOWN_SECONDS", "5"))

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# LLM parameters — moderate temperature for creative copy while
# preserving structural compliance
LLM_TEMPERATURE: float = 0.4
LLM_MAX_TOKENS: int = 4096

# Number of posts per LLM batch call
# Balances context window size vs. number of API calls
BATCH_SIZE: int = int(os.getenv("CONTENT_GEN_BATCH_SIZE", "5"))

# Content types that require a reel script
REEL_CONTENT_TYPES: frozenset[str] = frozenset({"Reel", "Short Video"})

# Required fields in every reel script
REEL_SCRIPT_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "hook",
        "hook_type",
        "body",
        "cta_moment",
        "total_duration_seconds",
        "audio_note",
        "visual_note",
    }
)

# Required fields in every generated post
GENERATED_POST_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "post_number",
        "platform",
        "content_pillar",
        "content_type",
        "topic",
        "caption",
        "hashtags",
        "cta",
    }
)

# Immutable fields — values must match the input PostEntry exactly
IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "post_number",
        "platform",
        "content_pillar",
        "content_type",
        "topic",
    }
)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY4")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY4 environment variable is not set. "
            "Content generator node cannot call the LLM without it."
        )
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Context builder helpers
# ---------------------------------------------------------------------------

def _build_brand_context_block(
    brand_profile: dict[str, Any] | None,
    content_strategy: dict[str, Any],
) -> str:
    """
    Builds the brand context section injected into every batch prompt.
    Includes voice, tone, language, cultural adaptations, and do/don'ts.
    """
    if not brand_profile or brand_profile.get("_parse_error"):
        brand_lines = "  Brand profile unavailable — use industry defaults."
    else:
        tone_guidelines = content_strategy.get("tone_guidelines", {})
        brand_lines = (
            f"  Brand Tone       : {brand_profile.get('brand_tone', 'N/A')}\n"
            f"  Content Language : {brand_profile.get('content_language', 'N/A')}\n"
            f"  Cultural Context : {brand_profile.get('cultural_context', 'N/A')}\n"
            f"  Overall Voice    : {tone_guidelines.get('overall_voice', 'N/A')}\n"
            f"  Language Style   : {tone_guidelines.get('language_style', 'N/A')}\n"
            f"  Cultural Tone    : {tone_guidelines.get('cultural_adaptations', 'N/A')}"
        )
        do_list = tone_guidelines.get("do", [])
        dont_list = tone_guidelines.get("dont", [])
        if do_list:
            brand_lines += f"\n  Do               : {'; '.join(do_list)}"
        if dont_list:
            brand_lines += f"\n  Don't            : {'; '.join(dont_list)}"

    return brand_lines


def _build_pillar_context_block(
    content_pillars: list[ContentPillar],
) -> str:
    """
    Builds the pillar reference block so the LLM knows each pillar's
    tone, angles, and example topics when writing captions.
    """
    if not content_pillars:
        return "  No pillar context available."

    lines: list[str] = []
    for pillar in content_pillars:
        name = pillar.get("name", "Unknown")
        description = pillar.get("description", "")
        evidence = pillar.get("evidence", [])
        evidence_str = evidence[0] if evidence else "N/A"
        lines.append(
            f"  [{name}]\n"
            f"    Description : {description}\n"
            f"    Evidence    : {evidence_str}"
        )
    return "\n".join(lines)


def _build_hashtag_reference_block(
    trend_research_results: list[dict[str, Any]],
    trending_topics: list[str],
) -> str:
    """
    Extracts known hashtags from trend research results and trending
    topics to give the LLM a grounded hashtag pool to draw from.
    """
    known_hashtags: list[str] = []

    # Extract from synthesised hashtag findings
    for result in trend_research_results:
        if result.get("category") == "trending_hashtags":
            hashtag = result.get("hashtag", "")
            if hashtag and hashtag.startswith("#"):
                known_hashtags.append(
                    f"{hashtag} [{result.get('platform', 'N/A')}] "
                    f"— {result.get('volume_signal', 'N/A')}"
                )

    # Extract hashtag-like tokens from trending topics
    for topic in trending_topics:
        if topic.startswith("#"):
            known_hashtags.append(topic)

    if not known_hashtags:
        return "  No evidence-retrieved hashtags available."

    return "\n".join(f"  {h}" for h in known_hashtags[:30])


def _build_platform_rules_block(platforms: set[str]) -> str:
    """
    Builds a compact platform rules summary for the platforms
    present in the current batch.
    """
    lines: list[str] = []
    for platform in sorted(platforms):
        rules = PLATFORM_CAPTION_RULES.get(platform, {})
        if rules:
            min_ht, max_ht = rules.get("hashtag_count", (3, 10))
            lines.append(
                f"  {platform}:\n"
                f"    Max chars  : {rules.get('max_chars', 'N/A')}\n"
                f"    Optimal    : {rules.get('optimal_chars', 'N/A')} chars\n"
                f"    Hashtags   : {min_ht}–{max_ht}\n"
                f"    Note       : {rules.get('format_note', 'N/A')}"
            )
    return "\n".join(lines) if lines else "  No platform rules available."


# ---------------------------------------------------------------------------
# Batch human message builder
# ---------------------------------------------------------------------------

def _build_batch_human_message(
    batch: list[PostEntry],
    brand_name: str,
    brand_context_block: str,
    pillar_context_block: str,
    hashtag_reference_block: str,
) -> str:
    """
    Constructs the human-turn message for a single batch of post slots.

    Each batch message includes:
      - Brand voice and cultural context
      - Pillar tone references
      - Known hashtag pool
      - Platform rules for platforms present in this batch
      - Full post briefs for each slot in the batch

    Parameters
    ----------
    batch : list[PostEntry]
        Subset of content_calendar for this LLM call.
    brand_name : str
        Brand name for context.
    brand_context_block : str
        Pre-built brand voice block.
    pillar_context_block : str
        Pre-built pillar reference block.
    hashtag_reference_block : str
        Pre-built known hashtag pool.

    Returns
    -------
    str
        Fully formatted batch brief.
    """
    # Collect unique platforms in this batch for rules block
    batch_platforms: set[str] = {
        post.get("platform", "") for post in batch if post.get("platform")
    }
    platform_rules_block = _build_platform_rules_block(batch_platforms)

    # Build individual post briefs
    post_briefs: list[str] = []
    for post in batch:
        platform = post.get("platform", "")
        content_type = post.get("content_type", "")
        needs_script = content_type in REEL_CONTENT_TYPES

        evidence_sources = post.get("evidence_sources", [])
        evidence_str = (
            "; ".join(evidence_sources)
            if evidence_sources
            else "No specific evidence — use brand context and pillar tone"
        )

        local_tie_in = post.get("local_event_tie_in", None)
        local_tie_str = (
            f"\n    Local Event Tie-In: {local_tie_in}"
            if local_tie_in
            else ""
        )

        strategic_note = post.get("strategic_note", "")
        strategic_str = (
            f"\n    Strategic Note    : {strategic_note}"
            if strategic_note
            else ""
        )

        brief = (
            f"  POST {post.get('post_number', '?')}:\n"
            f"    post_number   : {post.get('post_number', '?')}\n"
            f"    platform      : {platform}\n"
            f"    content_pillar: {post.get('content_pillar', '')}\n"
            f"    content_type  : {content_type}\n"
            f"    topic         : {post.get('topic', '')}\n"
            f"    evidence      : {evidence_str}"
            f"{local_tie_str}"
            f"{strategic_str}\n"
            f"    reel_script   : {'REQUIRED' if needs_script else 'null'}"
        )
        post_briefs.append(brief)

    posts_block = "\n\n".join(post_briefs)

    message = (
        f"BRAND: {brand_name}\n"
        f"BATCH SIZE: {len(batch)} posts\n"
        f"{'=' * 60}\n"
        f"BRAND VOICE & CULTURAL CONTEXT\n"
        f"{'=' * 60}\n"
        f"{brand_context_block}\n"
        f"{'=' * 60}\n"
        f"CONTENT PILLAR REFERENCE\n"
        f"{'=' * 60}\n"
        f"{pillar_context_block}\n"
        f"{'=' * 60}\n"
        f"PLATFORM RULES FOR THIS BATCH\n"
        f"{'=' * 60}\n"
        f"{platform_rules_block}\n"
        f"{'=' * 60}\n"
        f"KNOWN HASHTAG POOL (evidence-retrieved)\n"
        f"{'=' * 60}\n"
        f"{hashtag_reference_block}\n"
        f"{'=' * 60}\n"
        f"POST BRIEFS — Generate content for each:\n"
        f"{'=' * 60}\n"
        f"{posts_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Generate fully populated content for all {len(batch)} posts above.\n"
        f"Return a JSON array of exactly {len(batch)} objects.\n"
        f"Every post_number, platform, content_pillar, content_type, "
        f"and topic must exactly match the input values.\n"
        f"Write captions that are platform-native and brand-voice-consistent.\n"
        f"Use only evidence-retrieved or pillar-derived hashtags.\n"
        f"Include reel_script for every post marked REQUIRED — "
        f"set null for all others.\n"
        f"Return ONLY the JSON array — no markdown, no preamble, "
        f"no commentary."
    )

    return message


# ---------------------------------------------------------------------------
# LLM call and parser
# ---------------------------------------------------------------------------

async def _call_llm_and_parse_batch(
    human_message: str,
    llm: ChatGroq,
    brand_name: str,
    batch_index: int,
) -> list[dict[str, Any]]:
    """
    Calls ChatGroq for one batch and parses the JSON array response.

    Parameters
    ----------
    human_message : str
        Batch brief from _build_batch_human_message.
    llm : ChatGroq
        Authenticated ChatGroq instance.
    brand_name : str
        Used for log context.
    batch_index : int
        Batch number for log context.

    Returns
    -------
    list[dict[str, Any]]
        Parsed list of generated post dicts.
        Returns empty list on parse failure.
    """
    messages = [
        SystemMessage(content=CONTENT_GENERATION_SYSTEM_PROMPT),
        HumanMessage(content=human_message),
    ]

    logger.debug(
        "[%s] Invoking LLM | batch=%d | model=%s | brand='%s'",
        NODE_NAME,
        batch_index,
        GROQ_MODEL,
        brand_name,
    )

    response = await llm.ainvoke(messages)
    raw_content: str = response.content

    if not raw_content or not raw_content.strip():
        logger.error(
            "[%s] Empty LLM response | batch=%d | brand='%s'",
            NODE_NAME,
            batch_index,
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

    # Unwrap object wrapper if present
    if cleaned.startswith("{"):
        try:
            wrapper = json.loads(cleaned)
            for key in ("posts", "content", "items", "results", "calendar"):
                if key in wrapper and isinstance(wrapper[key], list):
                    cleaned = json.dumps(wrapper[key])
                    break
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            logger.error(
                "[%s] Expected list, got %s | batch=%d | brand='%s'",
                NODE_NAME,
                type(parsed).__name__,
                batch_index,
                brand_name,
            )
            return []

        logger.debug(
            "[%s] Batch %d parsed | posts=%d | brand='%s'",
            NODE_NAME,
            batch_index,
            len(parsed),
            brand_name,
        )
        return parsed

    except json.JSONDecodeError as exc:
        logger.error(
            "[%s] JSON parse failure | batch=%d | brand='%s' | "
            "error=%s | preview='%s'",
            NODE_NAME,
            batch_index,
            brand_name,
            str(exc),
            cleaned[:300],
        )
        return []


# ---------------------------------------------------------------------------
# Per-post validator
# ---------------------------------------------------------------------------

def _validate_generated_post(
    generated: dict[str, Any],
    original: PostEntry,
    post_errors: list[str],
) -> PostEntry | None:
    """
    Validates a single generated post dict against its original
    PostEntry and platform rules, then merges content into a new
    PostEntry.

    Validation checks:
      1. All required fields present and non-empty.
      2. Immutable fields match the original PostEntry exactly.
      3. Caption length within platform max_chars.
      4. Hashtag count within platform bounds.
      5. Reel script present when content_type is Reel/Short Video.
      6. Reel script has all required fields when present.

    Parameters
    ----------
    generated : dict
        Raw generated post from LLM.
    original : PostEntry
        The input post slot this must match.
    post_errors : list[str]
        Mutable list — validation errors appended here.

    Returns
    -------
    PostEntry | None
        Merged PostEntry if valid, None if critically malformed.
    """
    if not isinstance(generated, dict):
        post_errors.append(
            f"Post {original.get('post_number')}: "
            f"generated output is not a dict."
        )
        return None

    post_num = original.get("post_number", "?")

    # ── Immutable fields: always restore from original silently ──────────
    # The LLM occasionally returns null/modified values for these.
    # We override with the original without logging — the value is
    # always recoverable, so an error entry would just be noise.
    for field in IMMUTABLE_FIELDS:
        original_val = original.get(field)
        if not generated.get(field):
            generated[field] = original_val

    # ── Required field presence (non-immutable fields only) ──────────────
    for field in GENERATED_POST_REQUIRED_FIELDS:
        if field in IMMUTABLE_FIELDS:
            continue  # already restored above
        value = generated.get(field)
        is_missing = value is None or (isinstance(value, str) and not value.strip())
        if is_missing:
            post_errors.append(
                f"Post {post_num}: missing required field '{field}'."
            )
            if field == "caption":
                return None

    # Always use original values for immutable fields
    platform: str = original.get("platform", "")
    content_type: str = original.get("content_type", "")

    # ── Caption length validation ─────────────────────────────────────────
    caption: str = generated.get("caption", "")
    rules = PLATFORM_CAPTION_RULES.get(platform, {})
    max_chars = rules.get("max_chars", 2200)

    if len(caption) > max_chars:
        post_errors.append(
            f"Post {post_num}: caption exceeds {max_chars} chars "
            f"for {platform} (got {len(caption)}). Truncating."
        )
        caption = caption[:max_chars]

    # ── Hashtag count validation ──────────────────────────────────────────
    hashtags: list[str] = generated.get("hashtags", [])
    if not isinstance(hashtags, list):
        post_errors.append(
            f"Post {post_num}: hashtags is not a list. Defaulting to []."
        )
        hashtags = []

    # Ensure all hashtags start with #
    hashtags = [
        h if h.startswith("#") else f"#{h}"
        for h in hashtags
        if isinstance(h, str) and h.strip()
    ]

    min_ht, max_ht = rules.get("hashtag_count", (3, 15))
    if len(hashtags) > max_ht:
        post_errors.append(
            f"Post {post_num}: {len(hashtags)} hashtags exceeds "
            f"max {max_ht} for {platform}. Trimming."
        )
        hashtags = hashtags[:max_ht]

    # ── CTA validation ────────────────────────────────────────────────────
    cta: str = generated.get("cta", "")
    if not cta or not cta.strip():
        post_errors.append(
            f"Post {post_num}: empty CTA. Using generic fallback."
        )
        cta = f"Follow us for more {platform} content."

    # ── Reel script validation ────────────────────────────────────────────
    reel_script: dict[str, Any] | None = None
    needs_script = content_type in REEL_CONTENT_TYPES

    if needs_script:
        raw_script = generated.get("reel_script")
        if not raw_script or not isinstance(raw_script, dict):
            post_errors.append(
                f"Post {post_num}: reel_script is required for "
                f"content_type '{content_type}' but is missing or null."
            )
            # Non-fatal — post is still usable without script
        else:
            missing_script_fields = [
                f for f in REEL_SCRIPT_REQUIRED_FIELDS
                if f not in raw_script or not raw_script[f]
            ]
            if missing_script_fields:
                post_errors.append(
                    f"Post {post_num}: reel_script missing fields: "
                    f"{missing_script_fields}."
                )
            reel_script = raw_script
    else:
        # Ensure non-reel posts don't accidentally have scripts
        reel_script = None

    # ── Evidence sources ──────────────────────────────────────────────────
    generated_evidence = generated.get("evidence_sources", [])
    original_evidence = original.get("evidence_sources", [])
    # Merge both — preserve original citations plus any LLM added ones
    merged_evidence: list[str] = list(
        dict.fromkeys(
            (original_evidence or []) + (generated_evidence or [])
        )
    )

    # ── Build merged PostEntry ────────────────────────────────────────────
    return PostEntry(
        # Immutable fields from original
        post_number=original.get("post_number", 0),
        week=original.get("week", 1),
        day_of_week=original.get("day_of_week", "Monday"),
        platform=platform,
        content_pillar=original.get("content_pillar", ""),
        content_type=content_type,
        topic=original.get("topic", ""),
        # Generated content fields
        caption=caption,
        hashtags=hashtags,
        cta=cta,
        reel_script=reel_script,
        # Merged evidence
        evidence_sources=merged_evidence,
    )


# ---------------------------------------------------------------------------
# Hashtag bank and CTA bank builders
# ---------------------------------------------------------------------------

def _build_hashtag_bank(
    generated_posts: list[PostEntry],
) -> dict[str, dict[str, list[str]]]:
    """
    Builds the master hashtag bank organised by platform and pillar.

    Shape: { platform: { pillar: [#tag1, #tag2, ...] } }

    Deduplicates within each platform/pillar bucket.

    Parameters
    ----------
    generated_posts : list[PostEntry]
        All successfully generated posts.

    Returns
    -------
    dict[str, dict[str, list[str]]]
        Nested hashtag bank.
    """
    bank: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for post in generated_posts:
        platform = post.get("platform", "")
        pillar = post.get("content_pillar", "")
        hashtags = post.get("hashtags", [])

        if not platform or not pillar:
            continue

        for tag in hashtags:
            if tag and tag not in seen[platform][pillar]:
                seen[platform][pillar].add(tag)
                bank[platform][pillar].append(tag)

    # Convert defaultdicts to plain dicts for JSON serialisation
    return {
        platform: dict(pillars)
        for platform, pillars in bank.items()
    }


def _build_cta_bank(
    generated_posts: list[PostEntry],
) -> list[str]:
    """
    Extracts and deduplicates all CTAs from generated posts into a
    reusable library for the campaign generator.

    Parameters
    ----------
    generated_posts : list[PostEntry]
        All successfully generated posts.

    Returns
    -------
    list[str]
        Deduplicated CTA strings.
    """
    seen: set[str] = set()
    ctas: list[str] = []

    for post in generated_posts:
        cta = post.get("cta", "").strip()
        if cta and cta not in seen:
            seen.add(cta)
            ctas.append(cta)

    return ctas


# ---------------------------------------------------------------------------
# Batch processor
# ---------------------------------------------------------------------------

async def _process_batch(
    batch: list[PostEntry],
    batch_index: int,
    llm: ChatGroq,
    brand_name: str,
    brand_context_block: str,
    pillar_context_block: str,
    hashtag_reference_block: str,
    post_errors: list[str],
) -> list[PostEntry]:
    """
    Processes a single batch of post slots through the LLM and
    returns a list of fully populated PostEntry objects.

    Posts that fail validation are logged but excluded from results —
    the original slot (with empty caption) is NOT returned as a
    fallback to avoid polluting the output with empty content.

    Parameters
    ----------
    batch : list[PostEntry]
        Post slots for this batch.
    batch_index : int
        Batch number for logging.
    llm : ChatGroq
        Authenticated LLM client.
    brand_name : str
        Used for log context.
    brand_context_block, pillar_context_block,
    hashtag_reference_block : str
        Pre-built context blocks shared across all batches.
    post_errors : list[str]
        Mutable list — errors from this batch appended here.

    Returns
    -------
    list[PostEntry]
        Successfully generated and validated PostEntry objects.
    """
    # Build batch message
    human_message = _build_batch_human_message(
        batch=batch,
        brand_name=brand_name,
        brand_context_block=brand_context_block,
        pillar_context_block=pillar_context_block,
        hashtag_reference_block=hashtag_reference_block,
    )

    # Call LLM
    generated_list = await _call_llm_and_parse_batch(
        human_message=human_message,
        llm=llm,
        brand_name=brand_name,
        batch_index=batch_index,
    )

    if not generated_list:
        post_errors.append(
            f"Batch {batch_index}: LLM returned no content for "
            f"{len(batch)} posts."
        )
        return []

    # Build a lookup from post_number to original PostEntry
    original_by_number: dict[int, PostEntry] = {
        int(post.get("post_number", 0)): post
        for post in batch
    }

    results: list[PostEntry] = []
    for generated in generated_list:
        post_num = int(generated.get("post_number", -1))
        original = original_by_number.get(post_num)

        if original is None:
            # Try to find by position if post_number is wrong
            if len(results) < len(batch):
                original = batch[len(results)]
                post_errors.append(
                    f"Batch {batch_index}: post_number mismatch "
                    f"(got {post_num}). "
                    f"Matching by position to post "
                    f"{original.get('post_number')}."
                )
            else:
                post_errors.append(
                    f"Batch {batch_index}: unmatched post_number {post_num}. "
                    f"Skipping."
                )
                continue

        validated = _validate_generated_post(
            generated=generated,
            original=original,
            post_errors=post_errors,
        )
        if validated is not None:
            results.append(validated)

    logger.debug(
        "[%s] Batch %d complete | input=%d | output=%d | brand='%s'",
        NODE_NAME,
        batch_index,
        len(batch),
        len(results),
        brand_name,
    )
    return results


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def content_generator_node(state: ContentState) -> dict[str, Any]:
    """
    Content Generator Node — LangGraph node entry point.

    Executes the full content generation pipeline:
      1. Extract inputs from state.
      2. Build shared context blocks (brand, pillars, hashtags).
      3. Slice calendar into batches.
      4. Process each batch through the LLM.
      5. Validate and merge generated content into PostEntries.
      6. Build hashtag_bank and cta_bank.
      7. Update generation_metadata.
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
    - Partial generation is acceptable — successful posts are returned
      even if some batches fail.
    - campaign_generator_node always runs after this node regardless
      of how many posts were generated.
    """
    # Rate-limit cooldown — prevents Groq free-tier 429s
    # when nodes fire back-to-back. Set GROQ_COOLDOWN_SECONDS=0
    # on paid Groq tier.
    if GROQ_COOLDOWN_SECONDS > 0:
        import logging as _log
        _log.getLogger(__name__).info(
            "[content_generator_node] Rate-limit cooldown | sleeping=%.1fs",
            GROQ_COOLDOWN_SECONDS,
        )
        await asyncio.sleep(GROQ_COOLDOWN_SECONDS)

    start_time = time.monotonic()

    # ----------------------------------------------------------------
    # Extract inputs from state
    # ----------------------------------------------------------------
    brand_name: str = state.get("brand_name", "")
    content_calendar: list[PostEntry] = list(
        state.get("content_calendar") or []
    )
    brand_profile: dict[str, Any] | None = state.get("brand_profile")
    content_strategy: dict[str, Any] = dict(
        state.get("content_strategy") or {}
    )
    content_pillars: list[ContentPillar] = list(
        state.get("content_pillars") or []
    )
    trend_research_results: list[dict[str, Any]] = list(
        state.get("trend_research_results") or []
    )
    trending_topics: list[str] = list(state.get("trending_topics") or [])
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
        "calendar_size=%d | batch_size=%d",
        NODE_NAME,
        run_id,
        brand_name,
        len(content_calendar),
        BATCH_SIZE,
    )

    # ----------------------------------------------------------------
    # Initialise output accumulators
    # ALL variables must be initialised here — before the try block —
    # so the return statement never hits an UnboundLocalError even
    # when an exception (e.g. Groq TPD rate limit) aborts execution
    # mid-way through the try block before these are assigned.
    # ----------------------------------------------------------------
    generated_posts: list[PostEntry] = []
    hashtag_bank: dict[str, Any] = {}
    cta_bank: list[str] = []
    node_errors: list[dict[str, str]] = []
    post_errors: list[str] = []
    execution_status: str = "success"

    try:
        # ------------------------------------------------------------
        # Step 1: Initialise LLM client
        # ------------------------------------------------------------
        llm = _get_llm()

        # ------------------------------------------------------------
        # Step 2: Build shared context blocks
        # These are computed once and reused across all batches.
        # ------------------------------------------------------------
        brand_context_block = _build_brand_context_block(
            brand_profile=brand_profile,
            content_strategy=content_strategy,
        )
        pillar_context_block = _build_pillar_context_block(
            content_pillars=content_pillars,
        )
        hashtag_reference_block = _build_hashtag_reference_block(
            trend_research_results=trend_research_results,
            trending_topics=trending_topics,
        )

        # ------------------------------------------------------------
        # Step 3: Slice calendar into batches
        # ------------------------------------------------------------
        batches: list[list[PostEntry]] = [
            content_calendar[i: i + BATCH_SIZE]
            for i in range(0, len(content_calendar), BATCH_SIZE)
        ]

        logger.info(
            "[%s] Processing %d batches of up to %d posts | brand='%s'",
            NODE_NAME,
            len(batches),
            BATCH_SIZE,
            brand_name,
        )

        # ------------------------------------------------------------
        # Step 4: Process each batch
        # ------------------------------------------------------------
        for batch_idx, batch in enumerate(batches, start=1):
            logger.debug(
                "[%s] Processing batch %d/%d | posts=%d | brand='%s'",
                NODE_NAME,
                batch_idx,
                len(batches),
                len(batch),
                brand_name,
            )

            batch_results = await _process_batch(
                batch=batch,
                batch_index=batch_idx,
                llm=llm,
                brand_name=brand_name,
                brand_context_block=brand_context_block,
                pillar_context_block=pillar_context_block,
                hashtag_reference_block=hashtag_reference_block,
                post_errors=post_errors,
            )
            generated_posts.extend(batch_results)

        # ------------------------------------------------------------
        # Step 5: Sort by post_number to restore calendar order
        # ------------------------------------------------------------
        generated_posts.sort(
            key=lambda p: int(p.get("post_number", 0))
        )

        # ------------------------------------------------------------
        # Step 6: Record post-level errors as node errors
        # ------------------------------------------------------------
        for pe in post_errors:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": pe,
                    "field": "generated_posts",
                }
            )

        if len(generated_posts) < len(content_calendar):
            execution_status = "partial"
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": (
                        f"Generated {len(generated_posts)} of "
                        f"{len(content_calendar)} posts. "
                        f"{len(content_calendar) - len(generated_posts)} "
                        f"posts failed generation."
                    ),
                    "field": "generated_posts",
                }
            )

        # ------------------------------------------------------------
        # Step 7: Build hashtag bank and CTA bank
        # ------------------------------------------------------------
        hashtag_bank = _build_hashtag_bank(generated_posts)
        cta_bank = _build_cta_bank(generated_posts)

        # ------------------------------------------------------------
        # Step 8: Update generation_metadata
        # ------------------------------------------------------------
        generation_metadata["posts_generated"] = len(generated_posts)

        logger.info(
            "[%s] Generation complete | brand='%s' | "
            "generated=%d | calendar=%d | status=%s | "
            "hashtag_bank_platforms=%d | cta_bank=%d",
            NODE_NAME,
            brand_name,
            len(generated_posts),
            len(content_calendar),
            execution_status,
            len(hashtag_bank),
            len(cta_bank),
        )

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
        err_str = str(exc)
        is_rate_limit = "rate_limit_exceeded" in err_str or "429" in err_str

        if is_rate_limit:
            # Extract retry hint
            retry_hint = ""
            if "Please try again in" in err_str:
                try:
                    retry_hint = " " + err_str.split("Please try again in")[1].split(".")[0].strip()
                except Exception:  # noqa: BLE001
                    pass

            logger.warning(
                "[%s] Groq rate limit hit mid-generation | brand='%s' | "
                "posts_saved=%d | retry_in=%s",
                NODE_NAME, brand_name, len(generated_posts), retry_hint.strip() or "unknown",
            )
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": (
                        f"Groq daily token limit (TPD) reached.{retry_hint} "
                        f"{len(generated_posts)} of {len(content_calendar)} posts "
                        f"were generated before the limit was hit. "
                        f"Wait and re-run, or upgrade at https://console.groq.com/settings/billing"
                    ),
                    "field": "content_generator_node",
                }
            )
            # Keep whatever was generated — partial is better than nothing
            execution_status = "partial" if generated_posts else "failed"
            if generated_posts:
                hashtag_bank = _build_hashtag_bank(generated_posts)
                cta_bank = _build_cta_bank(generated_posts)
                generation_metadata["posts_generated"] = len(generated_posts)
        else:
            logger.exception(
                "[%s] Unexpected error | brand='%s' | error=%s",
                NODE_NAME, brand_name, err_str,
            )
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": f"Unexpected error: {err_str}",
                    "field": "content_generator_node",
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
        "evidence_count": len(generated_posts),
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
        len(generated_posts),
        len(node_errors),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # ----------------------------------------------------------------
    return {
        "generated_posts": generated_posts,
        "hashtag_bank": hashtag_bank if generated_posts else {},
        "cta_bank": cta_bank if generated_posts else [],
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }