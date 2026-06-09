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

from brand_context_prompt import BRAND_CONTEXT_SYSTEM_PROMPT
from content_state import ContentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_NAME: str = "brand_context_node"

# Model identifier — centralised here so it propagates to generation_metadata
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Tavily search configuration
TAVILY_MAX_RESULTS: int = 5          # Per query — kept low to avoid noise
TAVILY_SEARCH_DEPTH: str = "advanced" # "basic" | "advanced"

# Number of targeted search queries to run for brand context
BRAND_CONTEXT_QUERY_COUNT: int = 3

# Minimum evidence sources required before accepting LLM output
MIN_EVIDENCE_SOURCES: int = 1

# LLM generation parameters
LLM_TEMPERATURE: float = 0.2         # Low temperature — we want precision, not creativity
LLM_MAX_TOKENS: int = 2048


# ---------------------------------------------------------------------------
# Tavily client factory
# Instantiated inside the node rather than at module level so the client
# is not created during import (respects lazy initialisation patterns and
# avoids failures in test environments without credentials).
# ---------------------------------------------------------------------------

def _get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "TAVILY_API_KEY environment variable is not set. "
            "Brand context node cannot retrieve grounded evidence without it."
        )
    return TavilyClient(api_key=api_key)


def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY1")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY1 environment variable is not set. "
            "Brand context node cannot call the LLM without it."
        )
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Search query builder
# Constructs targeted, evidence-specific queries rather than generic ones.
# Three queries cover: industry/market context, local audience behaviour,
# and competitive/cultural landscape.
# ---------------------------------------------------------------------------

def _build_search_queries(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
) -> list[str]:
    """
    Builds a focused set of Tavily search queries for brand context research.

    Returns three queries designed to retrieve:
      Q1 — Industry and market trends in the specific city/country
      Q2 — Target audience behaviour and demographics for this industry/location
      Q3 — Competitive landscape and cultural content trends in this market

    Parameters
    ----------
    brand_name : str
        Used to add brand-specific signals where helpful.
    industry : str
        The vertical to anchor market and audience queries.
    country : str
        Country for geographic scoping.
    city : str
        City for hyper-local context.

    Returns
    -------
    list[str]
        Exactly BRAND_CONTEXT_QUERY_COUNT search query strings.
    """
    queries = [
        # Q1: Market and industry context
        f"{industry} market trends {city} {country} 2024 2025",

        # Q2: Audience behaviour and demographics
        f"{industry} target audience consumer behaviour {city} {country}",

        # Q3: Social media and content culture in this market
        f"social media content trends {industry} {country} audience insights",
    ]

    logger.debug(
        "[%s] Built %d search queries for brand='%s'",
        NODE_NAME,
        len(queries),
        brand_name,
    )
    return queries


# ---------------------------------------------------------------------------
# Evidence retrieval
# ---------------------------------------------------------------------------

async def _retrieve_evidence(
    queries: list[str],
    tavily: TavilyClient,
    brand_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Executes all search queries via Tavily and returns structured results
    plus a flat list of source identifiers for the evidence audit trail.

    Parameters
    ----------
    queries : list[str]
        Search queries produced by _build_search_queries.
    tavily : TavilyClient
        Authenticated Tavily client.
    brand_name : str
        Used for log context only.

    Returns
    -------
    tuple[list[dict], list[str]]
        - raw_results: Full Tavily result objects, one list per query,
          flattened into a single list.
        - evidence_sources: Deduplicated list of source URLs/titles
          for brand_context_evidence in state.
    """
    raw_results: list[dict[str, Any]] = []
    evidence_sources: list[str] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            logger.debug(
                "[%s] Executing Tavily search | query='%s'",
                NODE_NAME,
                query,
            )
            response = tavily.search(
                query=query,
                max_results=TAVILY_MAX_RESULTS,
                search_depth=TAVILY_SEARCH_DEPTH,
            )
            results: list[dict[str, Any]] = response.get("results", [])

            for result in results:
                url: str = result.get("url", "")
                title: str = result.get("title", "")
                content: str = result.get("content", "")
                score: float = result.get("score", 0.0)

                # Deduplicate by URL
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    raw_results.append(
                        {
                            "query": query,
                            "url": url,
                            "title": title,
                            "snippet": content[:500],  # Cap snippet length
                            "score": score,
                        }
                    )
                    # Source label: prefer title, fall back to URL
                    evidence_sources.append(title if title else url)

            logger.debug(
                "[%s] Query returned %d results | query='%s'",
                NODE_NAME,
                len(results),
                query,
            )

        except Exception as exc:  # noqa: BLE001
            # Non-fatal: log the failure and continue with remaining queries.
            # If all queries fail, the evidence guard will catch the empty result.
            logger.warning(
                "[%s] Tavily search failed | query='%s' | error=%s",
                NODE_NAME,
                query,
                str(exc),
            )

    logger.info(
        "[%s] Evidence retrieval complete | brand='%s' | sources=%d",
        NODE_NAME,
        brand_name,
        len(evidence_sources),
    )
    return raw_results, evidence_sources


# ---------------------------------------------------------------------------
# Human message builder
# Combines brand inputs + retrieved evidence into a structured prompt body.
# ---------------------------------------------------------------------------

def _build_human_message(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    foundation_date: str,
    raw_results: list[dict[str, Any]],
) -> str:
    """
    Constructs the human-turn message passed to the LLM alongside the
    system prompt.

    Combines structured brand inputs with retrieved Tavily evidence so
    the model has everything it needs in a single, well-labelled context
    block. Formatting is intentionally plain — no markdown headers that
    could bleed into the JSON output.

    Parameters
    ----------
    brand_name, industry, country, city, foundation_date : str
        User-supplied brand inputs from ContentState.
    raw_results : list[dict]
        Tavily search results from _retrieve_evidence.

    Returns
    -------
    str
        Fully formatted human message string.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Format evidence block — each result labelled clearly
    evidence_lines: list[str] = []
    for i, result in enumerate(raw_results, start=1):
        evidence_lines.append(
            f"SOURCE {i}:\n"
            f"  Title   : {result.get('title', 'N/A')}\n"
            f"  URL     : {result.get('url', 'N/A')}\n"
            f"  Query   : {result.get('query', 'N/A')}\n"
            f"  Snippet : {result.get('snippet', 'N/A')}\n"
            f"  Score   : {result.get('score', 0.0):.2f}"
        )

    evidence_block = (
        "\n\n".join(evidence_lines)
        if evidence_lines
        else "NO EVIDENCE RETRIEVED — acknowledge this gap in your output."
    )

    message = (
        f"TODAY'S DATE: {today_str}\n"
        f"{'=' * 60}\n"
        f"BRAND INPUTS\n"
        f"{'=' * 60}\n"
        f"Brand Name      : {brand_name}\n"
        f"Industry        : {industry}\n"
        f"Country         : {country}\n"
        f"City            : {city}\n"
        f"Foundation Date : {foundation_date}\n"
        f"{'=' * 60}\n"
        f"RETRIEVED EVIDENCE ({len(raw_results)} sources)\n"
        f"{'=' * 60}\n"
        f"{evidence_block}\n"
        f"{'=' * 60}\n"
        f"INSTRUCTIONS\n"
        f"{'=' * 60}\n"
        f"Using ONLY the brand inputs and retrieved evidence above, produce "
        f"the Brand Context Profile JSON object. "
        f"Every field must be grounded in the evidence provided. "
        f"Compute brand_age_years from foundation_date to today's date. "
        f"Return ONLY the JSON object — no markdown, no preamble, no commentary."
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
    Sends the system + human messages to ChatGroq and parses the
    structured JSON response.

    Parameters
    ----------
    human_message : str
        Formatted human message from _build_human_message.
    llm : ChatGroq
        Authenticated ChatGroq client.
    brand_name : str
        Used for log context only.

    Returns
    -------
    dict[str, Any]
        Parsed brand profile dict. Returns an error-flagged dict if
        parsing fails rather than raising — the node handles the error
        gracefully and writes it to state.

    Notes
    -----
    - The response is expected to be raw JSON with no markdown fences.
    - If the model wraps it in ```json ... ``` despite instructions, the
      parser strips the fences before attempting JSON decode.
    """
    messages = [
        SystemMessage(content=BRAND_CONTEXT_SYSTEM_PROMPT),
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

    # Strip markdown fences if the model ignored the no-fence instruction
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:] if lines[0].startswith("```") else lines
        # Remove closing fence
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        cleaned = "\n".join(lines).strip()

    try:
        parsed: dict[str, Any] = json.loads(cleaned)
        logger.debug(
            "[%s] LLM response parsed successfully | brand='%s' | keys=%s",
            NODE_NAME,
            brand_name,
            list(parsed.keys()),
        )
        return parsed

    except json.JSONDecodeError as exc:
        logger.error(
            "[%s] JSON parse failure | brand='%s' | error=%s | raw_preview='%s'",
            NODE_NAME,
            brand_name,
            str(exc),
            cleaned[:200],
        )
        return {
            "_parse_error": f"JSON decode failed: {str(exc)}",
            "_raw_response": cleaned[:500],
        }


# ---------------------------------------------------------------------------
# Response validator
# Checks that mandatory fields are present and non-empty in the parsed dict.
# ---------------------------------------------------------------------------

_REQUIRED_PROFILE_FIELDS: list[str] = [
    "summary",
    "brand_age_years",
    "target_audience",
    "brand_tone",
    "unique_value_prop",
    "content_language",
    "cultural_context",
    "market_positioning",
    "audience_pain_points",
    "content_opportunities",
    "evidence_used",
]


def _validate_brand_profile(
    profile: dict[str, Any],
    brand_name: str,
) -> list[str]:
    """
    Validates that the parsed brand profile contains all required fields
    with non-empty values.

    Parameters
    ----------
    profile : dict
        Parsed LLM response.
    brand_name : str
        Used for log context.

    Returns
    -------
    list[str]
        List of validation error messages. Empty list means valid.
    """
    validation_errors: list[str] = []

    if "_parse_error" in profile:
        return [f"Parse error: {profile['_parse_error']}"]

    for field in _REQUIRED_PROFILE_FIELDS:
        value = profile.get(field)
        if value is None:
            validation_errors.append(f"Missing required field: '{field}'")
        elif isinstance(value, str) and not value.strip():
            validation_errors.append(f"Field '{field}' is an empty string.")
        elif isinstance(value, list) and len(value) == 0:
            validation_errors.append(f"Field '{field}' is an empty list.")

    if validation_errors:
        logger.warning(
            "[%s] Brand profile validation found %d issue(s) | brand='%s'",
            NODE_NAME,
            len(validation_errors),
            brand_name,
        )

    return validation_errors


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

async def brand_context_node(state: ContentState) -> dict[str, Any]:
    """
    Brand Context Node — LangGraph node entry point.

    Executes the full brand context pipeline:
      1. Extract inputs from state.
      2. Build Tavily search queries.
      3. Retrieve grounded evidence.
      4. Build structured human message.
      5. Call LLM and parse response.
      6. Validate the parsed profile.
      7. Return state updates.

    Parameters
    ----------
    state : ContentState
        Current graph state. Reads brand inputs and generation_metadata.

    Returns
    -------
    dict[str, Any]
        Partial ContentState update. LangGraph merges this into the
        full state automatically.

    Notes
    -----
    - This function never raises. All exceptions are caught, logged,
      and written to the errors list in state so the graph can decide
      how to route.
    - brand_context_evidence will be an empty list on total failure,
      which causes route_after_brand_context to halt the workflow.
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
    generation_metadata: dict[str, Any] = dict(
        state.get("generation_metadata") or {}
    )
    existing_errors: list[dict[str, str]] = list(state.get("errors") or [])
    existing_log: list[dict[str, Any]] = list(
        state.get("node_execution_log") or []
    )

    run_id: str = generation_metadata.get("run_id", "unknown")

    logger.info(
        "[%s] Starting | run_id=%s | brand='%s' | industry='%s' | city='%s, %s'",
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
    brand_profile: dict[str, Any] = {}
    brand_context_evidence: list[str] = []
    node_errors: list[dict[str, str]] = []
    execution_status: str = "success"

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
            brand_name=brand_name,
            industry=industry,
            country=country,
            city=city,
        )

        # ------------------------------------------------------------
        # Step 3: Retrieve evidence from Tavily
        # ------------------------------------------------------------
        raw_results, evidence_sources = await _retrieve_evidence(
            queries=queries,
            tavily=tavily,
            brand_name=brand_name,
        )

        if len(evidence_sources) < MIN_EVIDENCE_SOURCES:
            logger.warning(
                "[%s] Evidence below minimum threshold | "
                "found=%d | required=%d | brand='%s'",
                NODE_NAME,
                len(evidence_sources),
                MIN_EVIDENCE_SOURCES,
                brand_name,
            )
            node_errors.append(
                {
                    "node": NODE_NAME,
                    "message": (
                        f"Tavily returned fewer than {MIN_EVIDENCE_SOURCES} "
                        f"sources. Brand context may be ungrounded."
                    ),
                    "field": "brand_context_evidence",
                }
            )
            execution_status = "partial"

        brand_context_evidence = evidence_sources

        # ------------------------------------------------------------
        # Step 4: Build human message
        # ------------------------------------------------------------
        human_message = _build_human_message(
            brand_name=brand_name,
            industry=industry,
            country=country,
            city=city,
            foundation_date=foundation_date,
            raw_results=raw_results,
        )

        # ------------------------------------------------------------
        # Step 5: Call LLM and parse response
        # ------------------------------------------------------------
        parsed_profile = await _call_llm_and_parse(
            human_message=human_message,
            llm=llm,
            brand_name=brand_name,
        )

        # ------------------------------------------------------------
        # Step 6: Validate parsed profile
        # ------------------------------------------------------------
        validation_errors = _validate_brand_profile(
            profile=parsed_profile,
            brand_name=brand_name,
        )

        if validation_errors:
            for ve in validation_errors:
                node_errors.append(
                    {
                        "node": NODE_NAME,
                        "message": ve,
                        "field": "brand_profile",
                    }
                )
            # Degraded but not fatal — partial profile is better than
            # nothing if evidence was retrieved successfully
            execution_status = "partial"
            logger.warning(
                "[%s] Profile has %d validation issue(s) | brand='%s'",
                NODE_NAME,
                len(validation_errors),
                brand_name,
            )
        else:
            logger.info(
                "[%s] Brand profile validated successfully | brand='%s'",
                NODE_NAME,
                brand_name,
            )

        brand_profile = parsed_profile

        # ------------------------------------------------------------
        # Step 7: Update generation metadata
        # ------------------------------------------------------------
        generation_metadata["model_used"] = GROQ_MODEL

    except EnvironmentError as exc:
        # Missing API keys — fatal, cannot continue
        logger.error(
            "[%s] Environment configuration error | brand='%s' | error=%s",
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
        # Unexpected failure — log full traceback, mark as failed,
        # leave brand_context_evidence empty so the guard halts the graph
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
                "field": "brand_context_node",
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
        "evidence_count": len(brand_context_evidence),
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[%s] Complete | run_id=%s | brand='%s' | status=%s | "
        "evidence=%d | duration_ms=%d",
        NODE_NAME,
        run_id,
        brand_name,
        execution_status,
        len(brand_context_evidence),
        duration_ms,
    )

    # ----------------------------------------------------------------
    # Return partial state update
    # LangGraph merges this dict into the full ContentState.
    # Only keys present in this dict are updated — all other state
    # fields remain unchanged.
    # ----------------------------------------------------------------
    return {
        "brand_profile": brand_profile if brand_profile else None,
        "brand_context_evidence": brand_context_evidence,
        "generation_metadata": generation_metadata,
        "errors": existing_errors + node_errors,
        "node_execution_log": existing_log + [log_entry],
    }
