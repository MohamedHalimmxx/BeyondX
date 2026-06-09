from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from content_strategy_prompt import (
    CONTENT_STRATEGY_SYSTEM_PROMPT,
    MAX_PILLARS,
    MIN_PILLARS,
)
from content_state import ContentPillar, ContentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "content_strategy_node"

GROQ_COOLDOWN_SECONDS: float = float(os.getenv("GROQ_COOLDOWN_SECONDS", "5"))

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# LLM parameters — slightly higher tokens than brand context because the
# strategy document is more verbose (pillars + platform strategy + mix)
LLM_TEMPERATURE: float = 0.2
LLM_MAX_TOKENS: int = 4096

# Maximum number of trend results to include in the human message.
# Caps context length while keeping the highest-scoring evidence.
MAX_TREND_RESULTS_IN_PROMPT: int = 8

# Maximum competitor insights to surface in the human message
MAX_COMPETITOR_INSIGHTS_IN_PROMPT: int = 5

# Pillar percentage tolerance — sum must equal 100 within this margin
PILLAR_SUM_TOLERANCE: int = 1


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY5")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY5 environment variable is not set. "
            "Content strategy node cannot call the LLM without it."
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
    brand_profile: dict[str, Any] | None,
    trend_research_results: list[dict[str, Any]],
    trending_topics: list[str],
    local_trends: list[str],
    competitor_insights: list[dict[str, str]],
) -> str:
    """
    Constructs the human-turn message for the strategy LLM call.

    Assembles all upstream evidence into clearly labelled sections:
      - Brand inputs and profile
      - Trending topics (flat labels for quick reference)
      - Local trends and cultural moments
      - Competitor and consumer behaviour insights
      - Top scored raw evidence results

    Parameters
    ----------
    brand_name, industry, country, city : str
        Core brand parameters.
    social_platforms : list[str]
        Platforms the brand uses — strategy must cover all of them.
    posts_per_month : int
        Used to calibrate posting frequency recommendations.
    brand_profile : dict | None
        Output of brand_context_node.
    trend_research_results : list[dict]
        Master evidence list from trend_research_node.
    trending_topics : list[str]
        Flat topic labels from trend_research_node.
    local_trends : list[str]
        City/country signals from trend_research_node.
    competitor_insights : list[dict[str, str]]
        Competitive observations from trend_research_node.

    Returns
    -------
    str
        Fully formatted human message.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Brand profile block ───────────────────────────────────────────────
    if brand_profile and not brand_profile.get("_parse_error"):
        profile_lines = [
            f"  Summary          : {brand_profile.get('summary', 'N/A')}",
            f"  Brand Age        : {brand_profile.get('brand_age_years', 'N/A')} years",
            f"  Target Audience  : {brand_profile.get('target_audience', 'N/A')}",
            f"  Brand Tone       : {brand_profile.get('brand_tone', 'N/A')}",
            f"  Unique Value Prop: {brand_profile.get('unique_value_prop', 'N/A')}",
            f"  Content Language : {brand_profile.get('content_language', 'N/A')}",
            f"  Cultural Context : {brand_profile.get('cultural_context', 'N/A')}",
            f"  Market Positioning: {brand_profile.get('market_positioning', 'N/A')}",
        ]
        pain_points = brand_profile.get("audience_pain_points", [])
        if pain_points:
            profile_lines.append(
                f"  Audience Pain Points: {'; '.join(pain_points)}"
            )
        content_opps = brand_profile.get("content_opportunities", [])
        if content_opps:
            profile_lines.append(
                f"  Content Opportunities: {'; '.join(content_opps)}"
            )
        brand_profile_block = "\n".join(profile_lines)
    else:
        brand_profile_block = (
            "  Brand profile not available from previous node.\n"
            "  Build strategy from industry + location signals only."
        )

    # ── Trending topics block ─────────────────────────────────────────────
    topics_block = (
        "\n".join(f"  • {topic}" for topic in trending_topics)
        if trending_topics
        else "  No trending topics extracted from evidence."
    )

    # ── Local trends block ────────────────────────────────────────────────
    local_block = (
        "\n".join(f"  • {trend}" for trend in local_trends)
        if local_trends
        else "  No local trends extracted from evidence."
    )

    # ── Competitor insights block ─────────────────────────────────────────
    capped_insights = competitor_insights[:MAX_COMPETITOR_INSIGHTS_IN_PROMPT]
    if capped_insights:
        insight_lines = [
            f"  [{i+1}] {item.get('observation', 'N/A')}\n"
            f"       Source: {item.get('source', 'N/A')}"
            for i, item in enumerate(capped_insights)
        ]
        insights_block = "\n".join(insight_lines)
    else:
        insights_block = "  No competitor insights available from evidence."

    # ── Top evidence results block ────────────────────────────────────────
    # Filter to synthesised findings only and sort by score descending
    synthesised = [
        r for r in trend_research_results
        if r.get("type") == "synthesised_finding"
    ]
    raw_scored = sorted(
        [r for r in trend_research_results if r.get("type") == "raw_search_result"],
        key=lambda x: x.get("score", 0.0),
        reverse=True,
    )
    # Combine: synthesised findings first, then top raw results
    top_results = (synthesised + raw_scored)[:MAX_TREND_RESULTS_IN_PROMPT]

    if top_results:
        evidence_lines = []
        for i, result in enumerate(top_results, start=1):
            result_type = result.get("type", "")
            category = result.get("category", "general").replace("_", " ").upper()

            if result_type == "synthesised_finding":
                # Synthesised findings have richer structure
                evidence_lines.append(
                    f"  [{i}] [{category}] {result.get('trend_name') or result.get('topic') or result.get('format_name') or result.get('event_name') or result.get('holiday_name') or result.get('hashtag') or result.get('moment') or 'N/A'}\n"
                    f"       Description : {result.get('description') or result.get('context') or result.get('behavior_shift') or 'N/A'}\n"
                    f"       Source      : {result.get('source', 'N/A')}"
                )
            else:
                evidence_lines.append(
                    f"  [{i}] [{category}] {result.get('title', 'N/A')}\n"
                    f"       Snippet : {result.get('snippet', 'N/A')[:300]}\n"
                    f"       URL     : {result.get('url', 'N/A')}\n"
                    f"       Score   : {result.get('score', 0.0):.2f}"
                )
        evidence_block = "\n".join(evidence_lines)
    else:
        evidence_block = "  No trend evidence available. Strategy confidence will be low."

    # ── Platforms and budget block ────────────────────────────────────────
    platforms_str = ", ".join(social_platforms) if social_platforms else "Not specified"

    message = (
        f"TODAY'S DATE: {today_str}\n"
        f"{'=' * 60}\n"
        f"BRAND PARAMETERS\n"
        f"{'=' * 60}\n"
        f"  Brand Name      : {brand_name}\n"
        f"  Industry        : {industry}\n"
        f"  Country         : {country}\n"
        f"  City            : {city}\n"
        f"  Social Platforms: {platforms_str}\n"
        f"  Posts Per Month : {posts_per_month}\n"
        f"{'=' * 60}\n"
        f"BRAND PROFILE (from Brand Context Node)\n"
        f"{'=' * 60}\n"
        f"{brand_profile_block}\n"
        f"{'=' * 60}\n"
        f"TRENDING TOPICS ({len(trending_topics)} extracted)\n"
        f"{'=' * 60}\n"
        f"{topics_block}\n"
        f"{'=' * 60}\n"
        f"LOCAL TRENDS & CULTURAL MOMENTS ({len(local_trends)} extracted)\n"
        f"{'=' * 60}\n"
        f"{local_block}\n"
        f"{'=' * 60}\n"
        f"COMPETITOR & CONSUMER INSIGHTS ({len(capped_insights)} shown)\n"
        f"{'=' * 60}\n"
        f"{insights_block}\n"
        f"{'=' * 60}\n"
        f"TREND EVIDENCE ({len(top_results)} of {len(trend_research_results)} results shown)\n"
        f"{'=' * 60}\n"
        f"{evidence_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Using ONLY the brand context and trend evidence above:\n"
        f"1. Build a complete Content Strategy document for {brand_name}.\n"
        f"2. Cover ALL platforms listed: {platforms_str}.\n"
        f"3. Build {MIN_PILLARS}–{MAX_PILLARS} content pillars with percentages summing to 100.\n"
        f"4. Calibrate posting_frequency so total posts across all platforms\n"
        f"   approximate {posts_per_month} posts per month.\n"
        f"5. Cite every source used in sources_cited.\n"
        f"Return ONLY the JSON object — no markdown, no preamble, no commentary."
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
    Calls ChatGroq and parses the structured JSON strategy document.

    Parameters
    ----------
    human_message : str
        Formatted message from _build_human_message.
    llm : ChatGroq
        Authenticated ChatGroq instance.
    brand_name : str
        Used for log context.

    Returns
    -------
    dict[str, Any]
        Parsed strategy document or error-flagged dict on failure.
    """
    messages = [
        SystemMessage(content=CONTENT_STRATEGY_SYSTEM_PROMPT),
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
        return {"_parse_error": "LLM returned an empty response."}

    cleaned = raw_content.strip()
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
            "[%s] JSON parse failure | brand='%s' | error=%s | preview='%s'",
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
# Pillar validator and normaliser
# ---------------------------------------------------------------------------

def _validate_and_normalise_pillars(
    raw_pillars: list[Any],
    social_platforms: list[str],
    brand_name: str,
) -> tuple[list[ContentPillar], list[str]]:
    """
    Validates, normalises, and converts the raw pillar list from the
    LLM response into typed ContentPillar dicts.

    Validation checks:
      1. Pillar count is within [MIN_PILLARS, MAX_PILLARS].
      2. Each pillar has required fields: name, description, percentage,
         post_types, evidence_justification.
      3. Pillar percentages sum to 100 (within PILLAR_SUM_TOLERANCE).
      4. primary_platforms only reference valid social_platforms.

    Normalisation:
      - Clamps percentage sum to 100 if within tolerance by adjusting
        the largest pillar.
      - Removes invalid platform references from primary_platforms.

    Parameters
    ----------
    raw_pillars : list
        Raw pillar list from LLM JSON.
    social_platforms : list[str]
        Valid platforms from state.
    brand_name : str
        Used for log context.

    Returns
    -------
    tuple[list[ContentPillar], list[str]]
        - validated_pillars : Typed and normalised ContentPillar list.
        - validation_errors : List of error strings (empty = clean).
    """
    validation_errors: list[str] = []
    validated_pillars: list[ContentPillar] = []

    if not isinstance(raw_pillars, list) or len(raw_pillars) == 0:
        return [], ["content_pillars field is missing or empty."]

    # ── Count check ───────────────────────────────────────────────────────
    if len(raw_pillars) < MIN_PILLARS:
        validation_errors.append(
            f"Too few pillars: got {len(raw_pillars)}, "
            f"minimum is {MIN_PILLARS}."
        )
    if len(raw_pillars) > MAX_PILLARS:
        validation_errors.append(
            f"Too many pillars: got {len(raw_pillars)}, "
            f"maximum is {MAX_PILLARS}. Truncating to {MAX_PILLARS}."
        )
        raw_pillars = raw_pillars[:MAX_PILLARS]

    platforms_set = set(social_platforms)

    for idx, pillar in enumerate(raw_pillars):
        if not isinstance(pillar, dict):
            validation_errors.append(
                f"Pillar {idx + 1} is not a dict — skipped."
            )
            continue

        pillar_name = pillar.get("name", f"Pillar {idx + 1}")

        # Required field checks
        required_fields = [
            "name", "description", "percentage",
            "post_types", "evidence_justification",
        ]
        for field in required_fields:
            if not pillar.get(field):
                validation_errors.append(
                    f"Pillar '{pillar_name}' missing required field: '{field}'."
                )

        # Sanitise primary_platforms — remove any not in social_platforms
        raw_platforms = pillar.get("primary_platforms", [])
        if isinstance(raw_platforms, list):
            valid_platforms = [
                p for p in raw_platforms if p in platforms_set
            ]
            invalid_platforms = [
                p for p in raw_platforms if p not in platforms_set
            ]
            if invalid_platforms:
                validation_errors.append(
                    f"Pillar '{pillar_name}' references platforms not in "
                    f"social_platforms: {invalid_platforms}. Removed."
                )
        else:
            valid_platforms = []

        # Build typed ContentPillar
        validated_pillars.append(
            ContentPillar(
                name=pillar.get("name", f"Pillar {idx + 1}"),
                description=pillar.get("description", ""),
                percentage=int(pillar.get("percentage", 0)),
                post_types=pillar.get("post_types", []),
                evidence=_extract_pillar_evidence(pillar),
            )
        )

    # ── Percentage sum check and normalisation ────────────────────────────
    if validated_pillars:
        total_pct = sum(p.get("percentage", 0) for p in validated_pillars)
        delta = 100 - total_pct

        if abs(delta) > PILLAR_SUM_TOLERANCE:
            validation_errors.append(
                f"Pillar percentages sum to {total_pct}, not 100. "
                f"Delta={delta}. Adjusting largest pillar."
            )

        # Normalise: apply delta to the largest pillar
        if delta != 0 and validated_pillars:
            largest_idx = max(
                range(len(validated_pillars)),
                key=lambda i: validated_pillars[i].get("percentage", 0),
            )
            current = validated_pillars[largest_idx].get("percentage", 0)
            validated_pillars[largest_idx]["percentage"] = current + delta
            logger.debug(
                "[%s] Normalised pillar '%s' percentage: %d → %d",
                NODE_NAME,
                validated_pillars[largest_idx].get("name"),
                current,
                current + delta,
            )

    logger.info(
        "[%s] Pillar validation complete | brand='%s' | "
        "pillars=%d | errors=%d",
        NODE_NAME,
        brand_name,
        len(validated_pillars),
        len(validation_errors),
    )

    return validated_pillars, validation_errors


def _extract_pillar_evidence(pillar: dict[str, Any]) -> list[str]:
    """
    Extracts evidence references from a pillar dict into a flat list.
    Pulls from evidence_justification (str) and any source fields.
    """
    evidence: list[str] = []

    justification = pillar.get("evidence_justification", "")
    if justification and isinstance(justification, str):
        evidence.append(justification)

    # Some LLM outputs include an explicit sources list per pillar
    sources = pillar.get("sources", [])
    if isinstance(sources, list):
        evidence.extend([s for s in sources if isinstance(s, str)])

    return evidence


# ---------------------------------------------------------------------------
# Strategy document validator
# ---------------------------------------------------------------------------

def _validate_strategy_document(
    strategy: dict[str, Any],
    social_platforms: list[str],
    brand_name: str,
) -> list[str]:
    """
    Validates the top-level strategy document fields.

    Parameters
    ----------
    strategy : dict
        Parsed LLM output.
    social_platforms : list[str]
        Expected platforms to be covered.
    brand_name : str
        Used for log context.

    Returns
    -------
    list[str]
        Validation error messages. Empty list = valid.
    """
    errors: list[str] = []

    if "_parse_error" in strategy:
        return [f"Parse error: {strategy['_parse_error']}"]

    required_keys = [
        "strategic_goal",
        "audience_insight",
        "platform_strategy",
        "content_mix",
        "posting_frequency",
        "tone_guidelines",
        "content_pillars",
        "evidence_summary",
        "sources_cited",
    ]
    for key in required_keys:
        if not strategy.get(key):
            errors.append(f"Missing or empty required field: '{key}'.")

    # Validate platform coverage
    platform_strategy = strategy.get("platform_strategy", {})
    if isinstance(platform_strategy, dict):
        for platform in social_platforms:
            if platform not in platform_strategy:
                errors.append(
                    f"Platform '{platform}' from social_platforms has no "
                    f"entry in platform_strategy."
                )

    # Validate content mix sums to 100
    content_mix = strategy.get("content_mix", {})
    if isinstance(content_mix, dict):
        mix_keys = [
            "educational", "entertaining",
            "promotional", "community", "behind_the_scenes",
        ]
        mix_values = [
            int(content_mix.get(k, 0))
            for k in mix_keys
            if isinstance(content_mix.get(k), (int, float))
        ]
        if mix_values:
            mix_total = sum(mix_values)
            if abs(mix_total - 100) > PILLAR_SUM_TOLERANCE:
                errors.append(
                    f"Content mix percentages sum to {mix_total}, not 100."
                )

    # Validate sources
    sources = strategy.get("sources_cited", [])
    if not sources or not isinstance(sources, list):
        errors.append("sources_cited is empty or missing.")

    if errors:
        logger.warning(
            "[%s] Strategy validation found %d issue(s) | brand='%s'",
            NODE_NAME,
            len(errors),
            brand_name,
        )

    return errors


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def content_strategy_node(state: ContentState) -> dict[str, Any]:
    """
    Content Strategy Node — LangGraph node entry point.

    Executes the full strategy synthesis pipeline:
      1. Extract inputs from state.
      2. Build structured human message with all upstream evidence.
      3. Call LLM and parse strategy document.
      4. Validate strategy document.
      5. Extract and validate content pillars.
      6. Return state updates.

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
    - content_pillars will be empty on failure, halting the graph.
    """
    # Rate-limit cooldown — prevents Groq free-tier 429s
    # when nodes fire back-to-back. Set GROQ_COOLDOWN_SECONDS=0
    # on paid Groq tier.
    if GROQ_COOLDOWN_SECONDS > 0:
        import logging as _log
        _log.getLogger(__name__).info(
            "[content_strategy_node] Rate-limit cooldown | sleeping=%.1fs",
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
    brand_profile: dict[str, Any] | None = state.get("brand_profile")
    trend_research_results: list[dict[str, Any]] = list(
        state.get("trend_research_results") or []
    )
    trending_topics: list[str] = list(state.get("trending_topics") or [])
    local_trends: list[str] = list(state.get("local_trends") or [])
    competitor_insights: list[dict[str, str]] = list(
        state.get("competitor_insights") or []
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
        "trend_results=%d | topics=%d | platforms=%s",
        NODE_NAME,
        run_id,
        brand_name,
        len(trend_research_results),
        len(trending_topics),
        social_platforms,
    )

    # ----------------------------------------------------------------
    # Initialise output accumulators
    # ----------------------------------------------------------------
    content_strategy: dict[str, Any] = {}
    content_pillars: list[ContentPillar] = []
    strategy_evidence_used: list[str] = []
    node_errors: list[dict[str, str]] = []
    execution_status: str = "success"

    try:
        # ------------------------------------------------------------
        # Step 1: Initialise LLM client
        # ------------------------------------------------------------
        llm = _get_llm()

        # ------------------------------------------------------------
        # Step 2: Build human message
        # ------------------------------------------------------------
        human_message = _build_human_message(
            brand_name=brand_name,
            industry=industry,
            country=country,
            city=city,
            social_platforms=social_platforms,
            posts_per_month=posts_per_month,
            brand_profile=brand_profile,
            trend_research_results=trend_research_results,
            trending_topics=trending_topics,
            local_trends=local_trends,
            competitor_insights=competitor_insights,
        )

        # ------------------------------------------------------------
        # Step 3: Call LLM and parse
        # ------------------------------------------------------------
        parsed_strategy = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
        )

        # ------------------------------------------------------------
        # Step 4: Validate strategy document
        # ------------------------------------------------------------
        strategy_errors = _validate_strategy_document(
            strategy=parsed_strategy,
            social_platforms=social_platforms,
            brand_name=brand_name,
        )
        for se in strategy_errors:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": se,
                    "field": "content_strategy",
                }
            )
        if strategy_errors:
            execution_status = "partial"

        # ------------------------------------------------------------
        # Step 5: Extract and validate pillars
        # ------------------------------------------------------------
        raw_pillars = parsed_strategy.get("content_pillars", [])
        content_pillars, pillar_errors = _validate_and_normalise_pillars(
            raw_pillars=raw_pillars,
            social_platforms=social_platforms,
            brand_name=brand_name,
        )
        for pe in pillar_errors:
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": pe,
                    "field": "content_pillars",
                }
            )
        if pillar_errors:
            execution_status = "partial"

        # ------------------------------------------------------------
        # Step 6: Build strategy_evidence_used audit trail
        # ------------------------------------------------------------
        strategy_evidence_used = list(
            parsed_strategy.get("sources_cited", [])
        )

        # Also collect evidence references from individual pillars
        for pillar in content_pillars:
            pillar_evidence = pillar.get("evidence", [])
            if pillar_evidence:
                strategy_evidence_used.extend(pillar_evidence)

        # Deduplicate
        strategy_evidence_used = list(dict.fromkeys(strategy_evidence_used))

        # ------------------------------------------------------------
        # Step 7: Store clean strategy (without raw pillar list,
        # since pillars live in their own state field)
        # ------------------------------------------------------------
        content_strategy = {
            k: v
            for k, v in parsed_strategy.items()
            if k != "content_pillars"
        }

        # Update metadata evidence count
        total_prev = generation_metadata.get("total_evidence_sources", 0)
        generation_metadata["total_evidence_sources"] = (
            total_prev + len(strategy_evidence_used)
        )

        logger.info(
            "[%s] Strategy synthesis complete | brand='%s' | "
            "pillars=%d | evidence_used=%d | status=%s",
            NODE_NAME,
            brand_name,
            len(content_pillars),
            len(strategy_evidence_used),
            execution_status,
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
                "field": "content_strategy_node",
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
        "evidence_count": len(strategy_evidence_used),
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[%s] Complete | run_id=%s | brand='%s' | status=%s | "
        "pillars=%d | evidence=%d | duration_ms=%d",
        NODE_NAME,
        run_id,
        brand_name,
        execution_status,
        len(content_pillars),
        len(strategy_evidence_used),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # ----------------------------------------------------------------
    return {
        "content_strategy": content_strategy if content_strategy else None,
        "content_pillars": content_pillars if content_pillars else [],
        "strategy_evidence_used": strategy_evidence_used,
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }