from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from tavily import TavilyClient

from trend_research_prompt import (
    INSUFFICIENT_EVIDENCE_MARKER,
    TREND_RESEARCH_SYSTEM_PROMPT,
)
from content_state import ContentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "trend_research_node"

# Primary model. llama-3.3-70b-versatile on Groq free tier has a
# 12,000 TPM (tokens-per-minute) limit, which is tight when the system
# prompt is large. llama-3.1-8b-instant has a 20,000 TPM limit and is
# used as the automatic fallback when a 413 is received.
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_FALLBACK_MODEL: str = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")

# Tavily configuration — higher result count than brand context because
# trend research needs broader evidence coverage across 11 categories
TAVILY_MAX_RESULTS_PER_QUERY: int = 5
TAVILY_SEARCH_DEPTH: str = "advanced"

# LLM parameters — slightly higher temperature than brand context to
# allow nuanced synthesis across diverse evidence, still heavily constrained
LLM_TEMPERATURE: float = 0.1
LLM_MAX_TOKENS: int = 4096

# Minimum raw Tavily results required before calling the LLM
MIN_RAW_RESULTS: int = 2

# Minimum populated (non-INSUFFICIENT_EVIDENCE) fields in LLM output
# before accepting the response as usable
MIN_POPULATED_CATEGORIES: int = 2

# Snippet character cap per Tavily result.
# Groq free tier: 12,000 TPM. The system prompt consumes ~7,000 tokens,
# leaving ~5,000 for the human message + LLM output (4,096).
# That means the human message budget is roughly 900 tokens — very tight.
# Keeping snippets small is the primary lever to stay within budget.
SNIPPET_MAX_CHARS: int = 180

# Hard cap on how many evidence items are sent to the LLM.
# Even with short snippets, 39 results can exceed the budget.
# Mathematical safe max for the primary model (12,000 TPM):
#   system_prompt ~6,500 + LLM_MAX_TOKENS 4,096 + human_msg ~1,400 = 11,996 < 12,000
# Set to 17 to keep primary model requests safely under the TPM cap.
# The fallback model (20,000 TPM) will handle cases where even this is tight.
MAX_EVIDENCE_FOR_LLM: int = 17

# Approximate token budget for the human message (excluding system prompt
# and LLM output). Used by _estimate_tokens() to pre-flight the payload.
# Groq TPM 12,000 − system_prompt_est 6,500 − LLM_MAX_TOKENS 4,096 = 1,404.
# We use 1,200 as a conservative target with headroom.
HUMAN_MSG_TOKEN_BUDGET: int = 1_200

# Characters per token (rough universal approximation).
CHARS_PER_TOKEN: float = 4.0

# On a 413 / rate_limit_exceeded error, retry once with this fraction
# of the original evidence set before giving up.
RETRY_EVIDENCE_FRACTION: float = 0.5


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def _get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "TAVILY_API_KEY environment variable is not set. "
            "Trend research node cannot retrieve evidence without it."
        )
    return TavilyClient(api_key=api_key)


def _get_llm(model: str | None = None) -> ChatGroq:
    """Return a ChatGroq instance for the given model (defaults to GROQ_MODEL)."""
    api_key = os.getenv("GROQ_API_KEY6")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY6 environment variable is not set. "
            "Trend research node cannot call the LLM without it."
        )
    return ChatGroq(
        model=model or GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Search query builder
# Constructs one targeted query per research category, calibrated to the
# specific industry + country + city combination.
# ---------------------------------------------------------------------------

def _build_search_queries(
    industry: str,
    country: str,
    city: str,
    brand_name: str,
) -> list[dict[str, str]]:
    """
    Builds a labelled set of Tavily search queries, one per research
    category. Each query is tagged with its category so results can be
    attributed back to the correct output field.

    Parameters
    ----------
    industry : str
        Industry vertical from state.
    country : str
        Country from state.
    city : str
        City from state.
    brand_name : str
        Used for log context only.

    Returns
    -------
    list[dict[str, str]]
        Each item has 'category' and 'query' keys.
    """
    current_year = datetime.now(timezone.utc).year
    next_year = current_year + 1

    queries: list[dict[str, str]] = [
        # ── 1. Social media trends ───────────────────────────────────────
        {
            "category": "social_media_trends",
            "query": (
                f"social media trends {industry} {country} "
                f"{current_year} {next_year} viral content"
            ),
        },
        # ── 2. Platform-specific trends ──────────────────────────────────
        {
            "category": "social_media_trends",
            "query": (
                f"Instagram TikTok trends {industry} {city} "
                f"{current_year} engagement"
            ),
        },
        # ── 3. Industry trends ───────────────────────────────────────────
        {
            "category": "industry_trends",
            "query": (
                f"{industry} industry trends {country} "
                f"{current_year} market insights"
            ),
        },
        # ── 4. Viral topics ──────────────────────────────────────────────
        {
            "category": "viral_topics",
            "query": (
                f"viral topics {industry} social media "
                f"{country} {current_year}"
            ),
        },
        # ── 5. Trending content formats ──────────────────────────────────
        {
            "category": "trending_content_formats",
            "query": (
                f"trending content formats reels short video "
                f"{industry} {current_year}"
            ),
        },
        # ── 6. Seasonal events ───────────────────────────────────────────
        {
            "category": "seasonal_events",
            "query": (
                f"seasonal events {industry} {country} "
                f"{current_year} {next_year}"
            ),
        },
        # ── 7. Upcoming holidays ─────────────────────────────────────────
        {
            "category": "upcoming_holidays",
            "query": (
                f"public holidays {country} {current_year} "
                f"{next_year} official calendar"
            ),
        },
        # ── 8. Local events ──────────────────────────────────────────────
        {
            "category": "local_events",
            "query": (
                f"events {city} {industry} {current_year} "
                f"{next_year} festival conference"
            ),
        },
        # ── 9. Consumer behaviour ────────────────────────────────────────
        {
            "category": "consumer_behavior_changes",
            "query": (
                f"consumer behaviour {industry} {country} "
                f"{current_year} social media habits"
            ),
        },
        # ── 10. Trending hashtags ────────────────────────────────────────
        {
            "category": "trending_hashtags",
            "query": (
                f"trending hashtags {industry} {city} {country} "
                f"{current_year} Instagram TikTok"
            ),
        },
        # ── 11. Trending conversations ───────────────────────────────────
        {
            "category": "trending_conversations",
            "query": (
                f"trending conversations discussions {industry} "
                f"{country} social media {current_year}"
            ),
        },
        # ── 12. Local cultural moments ───────────────────────────────────
        {
            "category": "local_cultural_moments",
            "query": (
                f"cultural moments {city} {country} "
                f"{current_year} {next_year} celebrations"
            ),
        },
    ]

    logger.debug(
        "[%s] Built %d search queries | brand='%s' | industry='%s'",
        NODE_NAME,
        len(queries),
        brand_name,
        industry,
    )
    return queries


# ---------------------------------------------------------------------------
# Evidence retrieval
# ---------------------------------------------------------------------------

async def _retrieve_evidence(
    queries: list[dict[str, str]],
    tavily: TavilyClient,
    brand_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Executes all search queries via Tavily and returns a deduplicated
    flat list of results with category tags, plus a list of source
    identifiers for the evidence audit trail.

    Each result is tagged with its originating category so the LLM
    can attribute findings correctly in its structured output.

    Parameters
    ----------
    queries : list[dict[str, str]]
        Labelled queries from _build_search_queries.
    tavily : TavilyClient
        Authenticated Tavily client.
    brand_name : str
        Used for log context only.

    Returns
    -------
    tuple[list[dict], list[str]]
        - raw_results : Deduplicated, category-tagged Tavily results.
        - evidence_sources : Flat list of source labels for state.
    """
    raw_results: list[dict[str, Any]] = []
    evidence_sources: list[str] = []
    seen_urls: set[str] = set()

    for item in queries:
        category: str = item["category"]
        query: str = item["query"]

        try:
            logger.debug(
                "[%s] Tavily search | category='%s' | query='%s'",
                NODE_NAME,
                category,
                query,
            )

            response = tavily.search(
                query=query,
                max_results=TAVILY_MAX_RESULTS_PER_QUERY,
                search_depth=TAVILY_SEARCH_DEPTH,
            )
            results: list[dict[str, Any]] = response.get("results", [])

            for result in results:
                url: str = result.get("url", "")
                title: str = result.get("title", "")
                content: str = result.get("content", "")
                score: float = result.get("score", 0.0)

                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                raw_results.append(
                    {
                        "category": category,
                        "query": query,
                        "url": url,
                        "title": title,
                        "snippet": content[:SNIPPET_MAX_CHARS],
                        "score": score,
                    }
                )
                evidence_sources.append(title if title else url)

            logger.debug(
                "[%s] Query returned %d results | category='%s'",
                NODE_NAME,
                len(results),
                category,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] Tavily search failed | category='%s' | "
                "query='%s' | error=%s",
                NODE_NAME,
                category,
                query,
                str(exc),
            )

    logger.info(
        "[%s] Evidence retrieval complete | brand='%s' | "
        "total_sources=%d | unique_urls=%d",
        NODE_NAME,
        brand_name,
        len(evidence_sources),
        len(seen_urls),
    )
    return raw_results, evidence_sources


# ---------------------------------------------------------------------------
# Token budget utilities
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """
    Fast character-based token estimate (1 token ≈ 4 chars).
    Conservative enough to use as a pre-flight guard before an LLM call.
    """
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _select_evidence_for_llm(
    raw_results: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    """
    Selects the top-N evidence items by Tavily relevance score while
    preserving category diversity (at least one item per category if
    possible).

    Parameters
    ----------
    raw_results : list[dict]
        All deduplicated Tavily results.
    max_items : int
        Hard cap on items to include.

    Returns
    -------
    list[dict]
        Subset of raw_results, sorted descending by score, capped at
        max_items and guaranteed to include at least one item per
        category (up to the cap).
    """
    if len(raw_results) <= max_items:
        return raw_results

    # Group by category
    by_category: dict[str, list[dict[str, Any]]] = {}
    for r in raw_results:
        cat = r.get("category", "general")
        by_category.setdefault(cat, []).append(r)

    # Sort each category by score descending and take the best item first
    selected: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    for items in by_category.values():
        items_sorted = sorted(items, key=lambda x: x.get("score", 0.0), reverse=True)
        selected.append(items_sorted[0])   # one per category guaranteed
        remainder.extend(items_sorted[1:])

    # Fill remaining slots with highest-scoring leftovers
    remaining_slots = max_items - len(selected)
    if remaining_slots > 0:
        remainder_sorted = sorted(
            remainder, key=lambda x: x.get("score", 0.0), reverse=True
        )
        selected.extend(remainder_sorted[:remaining_slots])

    return selected[:max_items]


# ---------------------------------------------------------------------------
# Human message builder
# ---------------------------------------------------------------------------

def _build_human_message(
    industry: str,
    country: str,
    city: str,
    brand_name: str,
    brand_profile: dict[str, Any] | None,
    raw_results: list[dict[str, Any]],
    max_evidence: int = MAX_EVIDENCE_FOR_LLM,
) -> str:
    """
    Constructs the human-turn message passed to the LLM.

    Applies two token-budget controls before assembly:
    1. Evidence is capped at `max_evidence` items (top by Tavily score,
       with category diversity preserved).
    2. Each snippet is hard-capped at SNIPPET_MAX_CHARS characters.

    This ensures the human message stays within the token budget defined
    by HUMAN_MSG_TOKEN_BUDGET even when Tavily returns many results.

    Parameters
    ----------
    industry, country, city, brand_name : str
        Core research parameters.
    brand_profile : dict | None
        Output of brand_context_node.
    raw_results : list[dict]
        Category-tagged Tavily results from _retrieve_evidence.
    max_evidence : int
        Maximum evidence items to include (default MAX_EVIDENCE_FOR_LLM).

    Returns
    -------
    str
        Fully formatted human message string.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Evidence selection: cap and score-rank ────────────────────────────
    selected_results = _select_evidence_for_llm(raw_results, max_evidence)
    dropped = len(raw_results) - len(selected_results)
    if dropped > 0:
        logger.debug(
            "[%s] Evidence truncated for token budget | "
            "kept=%d | dropped=%d | brand='%s'",
            NODE_NAME,
            len(selected_results),
            dropped,
            brand_name,
        )

    # ── Brand context summary ─────────────────────────────────────────────
    if brand_profile and not brand_profile.get("_parse_error"):
        target_audience = brand_profile.get("target_audience", "N/A")
        brand_tone = brand_profile.get("brand_tone", "N/A")
        cultural_context = brand_profile.get("cultural_context", "N/A")
        content_language = brand_profile.get("content_language", "N/A")
        brand_context_block = (
            f"BRAND CONTEXT\n"
            f"Audience: {target_audience} | Tone: {brand_tone} | "
            f"Language: {content_language} | Culture: {cultural_context}\n"
        )
    else:
        brand_context_block = (
            "BRAND CONTEXT: Unavailable. Use industry + location only.\n"
        )

    # ── Evidence block grouped by category ───────────────────────────────
    results_by_category: dict[str, list[dict[str, Any]]] = {}
    for result in selected_results:
        cat = result.get("category", "general")
        results_by_category.setdefault(cat, []).append(result)

    evidence_sections: list[str] = []
    source_counter = 1

    for category, items in results_by_category.items():
        category_label = category.replace("_", " ").upper()
        section_lines: list[str] = [f"[{category_label}]"]
        for item in items:
            # Enforce snippet cap (already applied at retrieval, but
            # enforced again here as a belt-and-suspenders guard)
            snippet = (item.get("snippet") or "")[:SNIPPET_MAX_CHARS]
            title = (item.get("title") or "N/A")[:80]  # cap title too
            section_lines.append(
                f"  {source_counter}. {title} — {snippet}"
            )
            source_counter += 1
        evidence_sections.append("\n".join(section_lines))

    if evidence_sections:
        evidence_block = "\n".join(evidence_sections)
    else:
        evidence_block = (
            "NO EVIDENCE RETRIEVED. "
            f"Mark all categories as {INSUFFICIENT_EVIDENCE_MARKER}."
        )

    message = (
        f"Date:{today_str} Brand:{brand_name} Industry:{industry} "
        f"Country:{country} City:{city}\n"
        f"{brand_context_block}"
        f"EVIDENCE ({len(selected_results)} sources):\n"
        f"{evidence_block}\n"
        f"---\n"
        f"Using ONLY the evidence above, produce the Trend Research Report "
        f"JSON. Extract findings for all 11 categories. "
        f"Use {INSUFFICIENT_EVIDENCE_MARKER} where evidence is absent. "
        f"List cited sources in all_sources_used. "
        f"Return ONLY the JSON object, no markdown, no preamble."
    )

    estimated_tokens = _estimate_tokens(message)
    logger.debug(
        "[%s] Human message built | brand='%s' | "
        "evidence_items=%d | estimated_tokens=%d | budget=%d",
        NODE_NAME,
        brand_name,
        len(selected_results),
        estimated_tokens,
        HUMAN_MSG_TOKEN_BUDGET,
    )

    return message


# ---------------------------------------------------------------------------
# LLM call and response parser
# ---------------------------------------------------------------------------

def _is_rate_limit_error(exc: Exception) -> bool:
    """Returns True if the exception is a Groq 413 / TPM rate-limit error."""
    msg = str(exc).lower()
    return "413" in msg or "rate_limit_exceeded" in msg or "tokens per minute" in msg


async def _invoke_llm_with_messages(
    messages: list,
    llm: ChatGroq,
    brand_name: str,
    model_label: str,
) -> str:
    """
    Thin wrapper around llm.ainvoke that logs the model being used.
    Returns raw content string.
    """
    logger.debug(
        "[%s] Invoking LLM | model=%s | brand='%s'",
        NODE_NAME,
        model_label,
        brand_name,
    )
    response = await llm.ainvoke(messages)
    return response.content


async def _call_llm_and_parse(
    human_message: str,
    llm: ChatGroq,
    brand_name: str,
    raw_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Calls ChatGroq with the system + human messages and parses
    the structured JSON trend report.

    Retry strategy on 413 / TPM rate-limit errors
    -----------------------------------------------
    1. First attempt  : primary model (GROQ_MODEL) with full evidence.
    2. On 413         : rebuild human message with RETRY_EVIDENCE_FRACTION
                        of the evidence (top items by score) and retry
                        with the fallback model (GROQ_FALLBACK_MODEL).
    3. On second 413  : give up and return an error-flagged dict.

    Parameters
    ----------
    human_message : str
        Formatted message from _build_human_message (full evidence).
    llm : ChatGroq
        Authenticated ChatGroq instance (primary model).
    brand_name : str
        Used for log context.
    raw_results : list[dict] | None
        Original Tavily results — required for retry with reduced evidence.

    Returns
    -------
    dict[str, Any]
        Parsed trend report. Returns an error-flagged dict on failure.
    """
    messages = [
        SystemMessage(content=TREND_RESEARCH_SYSTEM_PROMPT),
        HumanMessage(content=human_message),
    ]

    raw_content: str = ""

    try:
        raw_content = await _invoke_llm_with_messages(
            messages, llm, brand_name, GROQ_MODEL
        )

    except Exception as exc:  # noqa: BLE001
        if not _is_rate_limit_error(exc):
            # Not a token error — re-raise so the caller handles it
            raise

        logger.warning(
            "[%s] 413 TPM limit hit on primary model '%s' | brand='%s' | "
            "retrying with fallback model '%s' and reduced evidence (%d%%).",
            NODE_NAME,
            GROQ_MODEL,
            brand_name,
            GROQ_FALLBACK_MODEL,
            int(RETRY_EVIDENCE_FRACTION * 100),
        )

        # ── Retry: rebuild message with reduced evidence ─────────────────
        if raw_results:
            reduced_max = max(
                1, int(len(raw_results) * RETRY_EVIDENCE_FRACTION)
            )
            retry_human_message = _build_human_message(
                # We only have access to the assembled message here, so we
                # reconstruct with reduced evidence from raw_results.
                # Parse params from the original message header is fragile;
                # instead pass raw_results and let the builder re-select.
                industry="",      # not used for evidence selection
                country="",
                city="",
                brand_name=brand_name,
                brand_profile=None,
                raw_results=raw_results,
                max_evidence=reduced_max,
            )
        else:
            # No raw_results available — pass the original message as-is
            # but switch to the fallback model which may have higher TPM
            retry_human_message = human_message

        retry_messages = [
            SystemMessage(content=TREND_RESEARCH_SYSTEM_PROMPT),
            HumanMessage(content=retry_human_message),
        ]
        fallback_llm = _get_llm(model=GROQ_FALLBACK_MODEL)

        try:
            raw_content = await _invoke_llm_with_messages(
                retry_messages, fallback_llm, brand_name, GROQ_FALLBACK_MODEL
            )
            logger.info(
                "[%s] Fallback model succeeded | model='%s' | brand='%s'",
                NODE_NAME,
                GROQ_FALLBACK_MODEL,
                brand_name,
            )
        except Exception as retry_exc:  # noqa: BLE001
            logger.error(
                "[%s] Fallback model also failed | model='%s' | "
                "brand='%s' | error=%s",
                NODE_NAME,
                GROQ_FALLBACK_MODEL,
                brand_name,
                str(retry_exc),
            )
            return {
                "_parse_error": (
                    f"Both primary ({GROQ_MODEL}) and fallback "
                    f"({GROQ_FALLBACK_MODEL}) models failed. "
                    f"Last error: {str(retry_exc)}"
                )
            }

    if not raw_content or not raw_content.strip():
        logger.error(
            "[%s] LLM returned empty response | brand='%s'",
            NODE_NAME,
            brand_name,
        )
        return {"_parse_error": "LLM returned an empty response."}

    # Strip markdown fences if present despite instructions
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        cleaned = "\n".join(lines).strip()

    try:
        parsed: dict[str, Any] = json.loads(cleaned)
        logger.debug(
            "[%s] LLM response parsed | brand='%s' | "
            "top-level keys=%s",
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
# Response validator
# ---------------------------------------------------------------------------

# Primary list-type categories in the LLM output.
# Each must be a non-empty list to count as "populated".
_PRIMARY_CATEGORIES: list[str] = [
    "social_media_trends",
    "industry_trends",
    "viral_topics",
    "trending_content_formats",
    "seasonal_events",
    "upcoming_holidays",
    "local_events",
    "consumer_behavior_changes",
    "trending_hashtags",
    "trending_conversations",
    "local_cultural_moments",
]


def _is_insufficient(value: Any) -> bool:
    """
    Returns True if a value represents the INSUFFICIENT_EVIDENCE sentinel.
    Handles the various forms it can appear in:
      - A string matching the marker
      - A list whose only item is the marker string
      - A list of dicts where every value is the marker
    """
    if isinstance(value, str):
        return value.strip() == INSUFFICIENT_EVIDENCE_MARKER

    if isinstance(value, list):
        if len(value) == 0:
            return True
        # Single-item list containing just the marker string
        if len(value) == 1 and isinstance(value[0], str):
            return value[0].strip() == INSUFFICIENT_EVIDENCE_MARKER
        # List of dicts — check if ALL values across ALL dicts are markers
        if all(isinstance(item, dict) for item in value):
            all_values = [
                v for item in value for v in item.values()
            ]
            return all(
                isinstance(v, str) and v.strip() == INSUFFICIENT_EVIDENCE_MARKER
                for v in all_values
            )

    return False


def _validate_trend_report(
    report: dict[str, Any],
    brand_name: str,
) -> tuple[list[str], int]:
    """
    Validates the parsed trend report.

    Checks:
    1. No parse error flag present.
    2. Required top-level keys exist.
    3. At least MIN_POPULATED_CATEGORIES categories have real evidence
       (not INSUFFICIENT_EVIDENCE).
    4. all_sources_used is non-empty.

    Parameters
    ----------
    report : dict
        Parsed LLM output.
    brand_name : str
        Used for log context.

    Returns
    -------
    tuple[list[str], int]
        - validation_errors : List of error messages (empty = valid).
        - populated_count : Number of categories with real evidence.
    """
    validation_errors: list[str] = []
    populated_count: int = 0

    if "_parse_error" in report:
        return [f"Parse error: {report['_parse_error']}"], 0

    # Check required top-level keys
    required_keys = _PRIMARY_CATEGORIES + ["all_sources_used", "research_metadata"]
    for key in required_keys:
        if key not in report:
            validation_errors.append(f"Missing required key: '{key}'")

    # Count populated categories
    for category in _PRIMARY_CATEGORIES:
        value = report.get(category)
        if value is not None and not _is_insufficient(value):
            populated_count += 1

    if populated_count < MIN_POPULATED_CATEGORIES:
        validation_errors.append(
            f"Only {populated_count} of {len(_PRIMARY_CATEGORIES)} categories "
            f"have real evidence. Minimum required: {MIN_POPULATED_CATEGORIES}."
        )

    # Validate sources
    sources = report.get("all_sources_used", [])
    if not sources or (
        isinstance(sources, list)
        and len(sources) == 1
        and _is_insufficient(sources[0])
    ):
        validation_errors.append(
            "all_sources_used is empty or contains only "
            "INSUFFICIENT_EVIDENCE markers."
        )

    if validation_errors:
        logger.warning(
            "[%s] Trend report validation issues | brand='%s' | "
            "errors=%d | populated_categories=%d",
            NODE_NAME,
            brand_name,
            len(validation_errors),
            populated_count,
        )
    else:
        logger.info(
            "[%s] Trend report validated | brand='%s' | "
            "populated_categories=%d / %d",
            NODE_NAME,
            brand_name,
            populated_count,
            len(_PRIMARY_CATEGORIES),
        )

    return validation_errors, populated_count


# ---------------------------------------------------------------------------
# State field extractors
# Flatten the LLM's nested JSON output into the flat state fields that
# downstream nodes expect.
# ---------------------------------------------------------------------------

def _extract_trend_research_results(
    report: dict[str, Any],
    raw_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Builds the master trend_research_results list.

    Combines the raw Tavily results with the LLM-synthesised findings
    so downstream nodes have both the raw evidence AND the analysed output
    in one place.

    Returns
    -------
    list[dict]
        Combined list of raw results + LLM-synthesised entries.
    """
    combined: list[dict[str, Any]] = []

    # Include raw Tavily results as the ground-truth evidence layer
    for item in raw_results:
        combined.append(
            {
                "type": "raw_search_result",
                "category": item.get("category", "general"),
                "query": item.get("query", ""),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "score": item.get("score", 0.0),
            }
        )

    # Append LLM-synthesised entries per category
    for category in _PRIMARY_CATEGORIES:
        items = report.get(category, [])
        if _is_insufficient(items):
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and not _is_insufficient(item):
                combined.append(
                    {
                        "type": "synthesised_finding",
                        "category": category,
                        **item,
                    }
                )

    return combined


def _extract_trending_topics(report: dict[str, Any]) -> list[str]:
    """
    Flattens social_media_trends, industry_trends, and viral_topics
    into a deduplicated list of topic label strings.

    These are the labels downstream nodes use for quick topic matching
    without needing to parse nested objects.
    """
    topics: list[str] = []
    seen: set[str] = set()

    source_categories = [
        ("social_media_trends", "trend_name"),
        ("industry_trends", "trend_name"),
        ("viral_topics", "topic"),
        ("trending_conversations", "conversation_topic"),
        ("trending_content_formats", "format_name"),
    ]

    for category, field in source_categories:
        items = report.get(category, [])
        if _is_insufficient(items) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            label = item.get(field, "")
            if (
                label
                and label.strip()
                and label.strip() != INSUFFICIENT_EVIDENCE_MARKER
                and label.strip() not in seen
            ):
                seen.add(label.strip())
                topics.append(label.strip())

    return topics


def _extract_competitor_insights(
    report: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Extracts competitor/industry observations from industry_trends and
    consumer_behavior_changes into the competitor_insights state field.
    """
    insights: list[dict[str, str]] = []

    industry_items = report.get("industry_trends", [])
    if not _is_insufficient(industry_items) and isinstance(industry_items, list):
        for item in industry_items:
            if not isinstance(item, dict) or _is_insufficient(item):
                continue
            insights.append(
                {
                    "observation": item.get("trend_name", "")
                    + ": "
                    + item.get("description", ""),
                    "source": item.get("source", ""),
                }
            )

    behaviour_items = report.get("consumer_behavior_changes", [])
    if not _is_insufficient(behaviour_items) and isinstance(behaviour_items, list):
        for item in behaviour_items:
            if not isinstance(item, dict) or _is_insufficient(item):
                continue
            insights.append(
                {
                    "observation": item.get("behavior_shift", ""),
                    "source": item.get("source", ""),
                }
            )

    return insights


def _extract_local_trends(report: dict[str, Any]) -> list[str]:
    """
    Extracts city/country-specific trend signals from local_events,
    local_cultural_moments, upcoming_holidays, and seasonal_events
    into a flat list of label strings.
    """
    labels: list[str] = []
    seen: set[str] = set()

    source_map = [
        ("local_events", "event_name"),
        ("local_cultural_moments", "moment"),
        ("upcoming_holidays", "holiday_name"),
        ("seasonal_events", "event_name"),
    ]

    for category, field in source_map:
        items = report.get(category, [])
        if _is_insufficient(items) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or _is_insufficient(item):
                continue
            label = item.get(field, "")
            if (
                label
                and label.strip()
                and label.strip() != INSUFFICIENT_EVIDENCE_MARKER
                and label.strip() not in seen
            ):
                seen.add(label.strip())
                labels.append(label.strip())

    return labels


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def trend_research_node(state: ContentState) -> dict[str, Any]:
    """
    Trend Research Node — LangGraph node entry point.

    Executes the full trend research pipeline:
      1. Extract inputs from state.
      2. Build targeted Tavily search queries for all 11 categories.
      3. Retrieve and deduplicate evidence.
      4. Build structured human message with brand context.
      5. Call LLM and parse structured trend report.
      6. Validate the parsed report.
      7. Flatten output into state fields.
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
    - Never raises. All exceptions are caught and written to errors.
    - trend_research_results will be empty on total failure, causing
      route_after_trend_research to halt the graph.
    """
    start_time = time.monotonic()

    # ----------------------------------------------------------------
    # Extract inputs from state
    # ----------------------------------------------------------------
    brand_name: str = state.get("brand_name", "")
    industry: str = state.get("industry", "")
    country: str = state.get("country", "")
    city: str = state.get("city", "")
    brand_profile: dict[str, Any] | None = state.get("brand_profile")
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
        "industry='%s' | city='%s, %s'",
        NODE_NAME,
        run_id,
        brand_name,
        industry,
        city,
        country,
    )

    # ----------------------------------------------------------------
    # Initialise output accumulators
    # ----------------------------------------------------------------
    trend_research_results: list[dict[str, Any]] = []
    trending_topics: list[str] = []
    competitor_insights: list[dict[str, str]] = []
    local_trends: list[str] = []
    node_errors: list[dict[str, str]] = []
    execution_status: str = "success"
    evidence_count: int = 0

    try:
        # ------------------------------------------------------------
        # Step 1: Initialise clients
        # ------------------------------------------------------------
        tavily = _get_tavily_client()
        llm = _get_llm()

        # ------------------------------------------------------------
        # Step 2: Build search queries
        # ------------------------------------------------------------
        queries = _build_search_queries(
            industry=industry,
            country=country,
            city=city,
            brand_name=brand_name,
        )

        # ------------------------------------------------------------
        # Step 3: Retrieve evidence
        # ------------------------------------------------------------
        raw_results, evidence_sources = await _retrieve_evidence(
            queries=queries,
            tavily=tavily,
            brand_name=brand_name,
        )
        evidence_count = len(evidence_sources)

        if evidence_count < MIN_RAW_RESULTS:
            logger.warning(
                "[%s] Low evidence volume | found=%d | "
                "minimum=%d | brand='%s'",
                NODE_NAME,
                evidence_count,
                MIN_RAW_RESULTS,
                brand_name,
            )
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": (
                        f"Tavily returned only {evidence_count} results. "
                        f"Trend report quality may be degraded."
                    ),
                    "field": "trend_research_results",
                }
            )
            execution_status = "partial"

        # ------------------------------------------------------------
        # Step 4: Build human message
        # ------------------------------------------------------------
        human_message = _build_human_message(
            industry=industry,
            country=country,
            city=city,
            brand_name=brand_name,
            brand_profile=brand_profile,
            raw_results=raw_results,
        )

        # ------------------------------------------------------------
        # Step 5: Call LLM and parse (with auto-retry on 413)
        # ------------------------------------------------------------
        parsed_report = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
            raw_results=raw_results,   # passed for reduced-evidence retry
        )

        # ------------------------------------------------------------
        # Step 6: Validate
        # ------------------------------------------------------------
        validation_errors, populated_count = _validate_trend_report(
            report=parsed_report,
            brand_name=brand_name,
        )

        if validation_errors:
            for ve in validation_errors:
                node_errors.append(
                    {
                        "node": NODE_NAME,
                        "message": ve,
                        "field": "trend_research_results",
                    }
                )
            execution_status = "partial"

        # Log evidence gaps from the LLM's own assessment
        evidence_gaps: list[str] = parsed_report.get("evidence_gaps", [])
        if evidence_gaps:
            logger.info(
                "[%s] LLM-reported evidence gaps | brand='%s' | gaps=%s",
                NODE_NAME,
                brand_name,
                evidence_gaps,
            )

        # ------------------------------------------------------------
        # Step 7: Flatten LLM output into state fields
        # ------------------------------------------------------------
        trend_research_results = _extract_trend_research_results(
            report=parsed_report,
            raw_results=raw_results,
        )
        trending_topics = _extract_trending_topics(report=parsed_report)
        competitor_insights = _extract_competitor_insights(report=parsed_report)
        local_trends = _extract_local_trends(report=parsed_report)

        # Update total evidence count in metadata
        total_prev = generation_metadata.get("total_evidence_sources", 0)
        generation_metadata["total_evidence_sources"] = (
            total_prev + len(
                parsed_report.get("all_sources_used", evidence_sources)
            )
        )

        logger.info(
            "[%s] Extraction complete | brand='%s' | "
            "results=%d | topics=%d | local_trends=%d | "
            "competitor_insights=%d",
            NODE_NAME,
            brand_name,
            len(trend_research_results),
            len(trending_topics),
            len(local_trends),
            len(competitor_insights),
        )

    except EnvironmentError as exc:
        logger.error(
            "[%s] Environment configuration error | "
            "brand='%s' | error=%s",
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
                "field": "trend_research_node",
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
        "evidence_count": evidence_count,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[%s] Complete | run_id=%s | brand='%s' | status=%s | "
        "evidence=%d | topics=%d | local_trends=%d | duration_ms=%d",
        NODE_NAME,
        run_id,
        brand_name,
        execution_status,
        evidence_count,
        len(trending_topics),
        len(local_trends),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # ----------------------------------------------------------------
    return {
        "trend_research_results": (
            trend_research_results if trend_research_results else []
        ),
        "trending_topics": trending_topics,
        "competitor_insights": competitor_insights,
        "local_trends": local_trends,
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }