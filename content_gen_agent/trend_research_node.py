from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
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

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Tavily configuration — higher result count than brand context because
# trend research needs broader evidence coverage across 11 categories
TAVILY_MAX_RESULTS_PER_QUERY: int = 3
TAVILY_SEARCH_DEPTH: str = "advanced"

# LLM parameters — slightly higher temperature than brand context to
# allow nuanced synthesis across diverse evidence, still heavily constrained
LLM_TEMPERATURE: float = 0.1
LLM_MAX_TOKENS: int = 2500

# Minimum raw Tavily results required before calling the LLM
MIN_RAW_RESULTS: int = 2

# Minimum populated (non-INSUFFICIENT_EVIDENCE) fields in LLM output
# before accepting the response as usable
MIN_POPULATED_CATEGORIES: int = 2

# Snippet character cap per Tavily result — keeps human message within
# context window limits when many queries return many results
SNIPPET_MAX_CHARS: int = 200


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


def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY environment variable is not set. "
            "Trend research node cannot call the LLM without it."
        )
    return ChatGroq(
        model=GROQ_MODEL,
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
    now = datetime.now(timezone.utc)
    current_year = now.year
    next_year = current_year + 1
    today_str = now.strftime("%Y-%m-%d")
    current_month = now.strftime("%B %Y")   # e.g. "June 2026"

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
                f"upcoming seasonal events {industry} {country} "
                f"after {current_month} {next_year}"
            ),
        },
        # ── 7. Upcoming holidays ─────────────────────────────────────────
        # Explicitly ask AFTER today so Tavily won't return holidays
        # that have already passed (e.g. Ramadan if it ended months ago).
        {
            "category": "upcoming_holidays",
            "query": (
                f"upcoming public holidays {country} after {current_month} "
                f"{current_year} {next_year} official calendar"
            ),
        },
        # ── 8. Local events ──────────────────────────────────────────────
        {
            "category": "local_events",
            "query": (
                f"upcoming events {city} {industry} after {current_month} "
                f"{current_year} {next_year} festival conference"
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
            err_str = str(exc).lower()
            is_billing = any(
                kw in err_str
                for kw in ("usage limit", "quota", "billing", "upgrade", "plan")
            )
            if is_billing:
                logger.warning(
                    "[%s] Tavily billing/quota limit reached | category='%s' | "
                    "Switching to LLM-only mode for remaining queries.",
                    NODE_NAME,
                    category,
                )
                # Inject fallback sentinel and stop all remaining queries
                if not any("TAVILY_UNAVAILABLE" in s for s in evidence_sources):
                    evidence_sources.append(
                        "[TAVILY_UNAVAILABLE] Tavily quota exhausted — "
                        "trend research generated from LLM knowledge only."
                    )
                    raw_results.append({
                        "category": "tavily_unavailable",
                        "query": query,
                        "url": "tavily_unavailable",
                        "title": "[TAVILY_UNAVAILABLE] Tavily quota exhausted",
                        "snippet": "Tavily search unavailable. LLM knowledge used as fallback.",
                        "score": 0.0,
                    })
                break
            else:
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
# Human message builder
# ---------------------------------------------------------------------------

def _build_human_message(
    industry: str,
    country: str,
    city: str,
    brand_name: str,
    brand_profile: dict[str, Any] | None,
    raw_results: list[dict[str, Any]],
) -> str:
    """
    Constructs the human-turn message passed to the LLM.

    Combines research parameters, brand context summary from the
    previous node, and the full retrieved evidence block.

    Parameters
    ----------
    industry, country, city, brand_name : str
        Core research parameters.
    brand_profile : dict | None
        Output of brand_context_node. Used to enrich the research
        context — e.g. target audience informs which trends are relevant.
    raw_results : list[dict]
        Category-tagged Tavily results from _retrieve_evidence.

    Returns
    -------
    str
        Fully formatted human message string.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Brand context summary ─────────────────────────────────────────────
    if brand_profile and not brand_profile.get("_parse_error"):
        brand_context_block = (
            f"BRAND CONTEXT\n"
            f"Audience: {brand_profile.get('target_audience', 'N/A')}\n"
            f"Tone: {brand_profile.get('brand_tone', 'N/A')}\n"
            f"Language: {brand_profile.get('content_language', 'N/A')}\n"
        )
    else:
        brand_context_block = "BRAND CONTEXT: Not available.\n" 

    # ── Evidence block grouped by category ───────────────────────────────
    # Group results by category, capped at 2 per category to keep
    # the prompt within Groq free-tier TPM limits.
    MAX_RESULTS_PER_CATEGORY_IN_PROMPT: int = 2

    results_by_category: dict[str, list[dict[str, Any]]] = {}
    for result in raw_results:
        cat = result.get("category", "general")
        results_by_category.setdefault(cat, []).append(result)

    evidence_sections: list[str] = []
    source_counter = 1

    for category, items in results_by_category.items():
        category_label = category.replace("_", " ").upper()
        # Cap results per category to control prompt size
        capped_items = items[:MAX_RESULTS_PER_CATEGORY_IN_PROMPT]
        section_lines: list[str] = [
            f"CATEGORY: {category_label} ({len(capped_items)}/{len(items)} sources shown)"
        ]
        for item in capped_items:
            section_lines.append(
                f"  [{source_counter}] {item.get('title', 'N/A')}\n"
                f"       {item.get('snippet', 'N/A')}"
            )
            source_counter += 1
        evidence_sections.append("\n".join(section_lines))

    if evidence_sections:
        evidence_block = "\n\n".join(evidence_sections)
    else:
        evidence_block = (
            "NO EVIDENCE RETRIEVED.\n"
            "All research categories must be marked as "
            f"{INSUFFICIENT_EVIDENCE_MARKER}."
        )

    message = (
        f"TODAY'S DATE: {today_str}\n"
        f"{'=' * 60}\n"
        f"RESEARCH PARAMETERS\n"
        f"{'=' * 60}\n"
        f"Brand Name : {brand_name}\n"
        f"Industry   : {industry}\n"
        f"Country    : {country}\n"
        f"City       : {city}\n"
        f"{'=' * 60}\n"
        f"{brand_context_block}"
        f"{'=' * 60}\n"
        f"RETRIEVED EVIDENCE ({len(raw_results)} total sources "
        f"across {len(results_by_category)} categories)\n"
        f"{'=' * 60}\n"
        f"{evidence_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Using ONLY the retrieved evidence above, produce the Trend "
        f"Research Report JSON object. "
        f"Extract findings for all 11 research categories. "
        f"CRITICAL DATE RULE: Today is {today_str}. "
        f"For upcoming_holidays and seasonal_events and local_events: "
        f"ONLY include events whose date is AFTER today ({today_str}). "
        f"If an event (e.g. Ramadan, Eid, a festival) has already passed "
        f"before today, you MUST exclude it completely — do NOT include it "
        f"even if the evidence mentions it. "
        f"A past event as a campaign recommendation is a critical error. "
        f"Use {INSUFFICIENT_EVIDENCE_MARKER} for any category where "
        f"evidence is absent. "
        f"List every source you cited in all_sources_used. "
        f"Return ONLY the JSON object — no markdown, no preamble, "
        f"no commentary."
    )

    return message


# ---------------------------------------------------------------------------
# LLM call and response parser
# ---------------------------------------------------------------------------

async def _call_llm_and_parse(
    human_message: str,
    llm: ChatGroq,
    brand_name: str,
) -> dict[str, Any]:
    """
    Calls ChatGroq with the system + human messages and parses
    the structured JSON trend report.

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
        Parsed trend report. Returns an error-flagged dict on failure.
    """
    messages = [
        SystemMessage(content=TREND_RESEARCH_SYSTEM_PROMPT),
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


def _is_event_in_past(item: dict[str, Any]) -> bool:
    """
    Returns True if a holiday/event item has a date field that parses
    to a date strictly before today. Used to filter out past events
    that Tavily returned despite being asked for upcoming-only results.

    Checks the 'date', 'date_or_period', and 'anniversary_date' fields.
    Returns False (keep the item) when the date cannot be parsed —
    better to include an unverifiable event than to silently drop it.
    """
    today = date.today()
    date_fields = ["date", "date_or_period", "anniversary_date", "timing"]

    for field in date_fields:
        raw = item.get(field, "")
        if not raw or not isinstance(raw, str):
            continue

        # Try common date formats
        for fmt in ("%Y-%m-%d", "%Y-%m", "%B %Y", "%b %Y"):
            try:
                parsed = datetime.strptime(raw.strip()[:10], fmt).date()
                if parsed < today:
                    return True  # Past event — exclude
                return False     # Future event — keep
            except ValueError:
                continue

        # Check for year-only match — if it is a past year, exclude
        import re
        year_match = re.search(r"\b(20\d{2})\b", raw)
        if year_match:
            year = int(year_match.group(1))
            if year < today.year:
                return True  # Past year — exclude
            if year > today.year:
                return False  # Future year — keep
            # Same year — cannot determine month, keep it
            return False

    return False  # No parseable date — keep by default


def _extract_local_trends(report: dict[str, Any]) -> list[str]:
    """
    Extracts city/country-specific trend signals from local_events,
    local_cultural_moments, upcoming_holidays, and seasonal_events
    into a flat list of label strings.

    Filters out any event whose date field parses to before today
    to prevent past events (e.g. a Ramadan that ended months ago)
    from appearing as campaign recommendations.
    """
    labels: list[str] = []
    seen: set[str] = set()
    skipped: list[str] = []

    source_map = [
        ("local_events",          "event_name"),
        ("local_cultural_moments","moment"),
        ("upcoming_holidays",     "holiday_name"),
        ("seasonal_events",       "event_name"),
    ]

    for category, field in source_map:
        items = report.get(category, [])
        if _is_insufficient(items) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or _is_insufficient(item):
                continue

            # Skip events whose date is in the past
            if _is_event_in_past(item):
                label = item.get(field, "unknown")
                skipped.append(f"{label} (past event — excluded)")
                logger.debug(
                    "Past event filtered out from local_trends: %s", label
                )
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

    if skipped:
        logger.info(
            "Past events filtered from local_trends: %s", skipped
        )

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
        # Step 5: Call LLM and parse
        # ------------------------------------------------------------
        parsed_report = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
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