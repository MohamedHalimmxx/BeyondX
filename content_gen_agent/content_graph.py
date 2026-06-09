from __future__ import annotations

import asyncio
import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph

from brand_context_node import brand_context_node
from calendar_builder_node import calendar_builder_node
from campaign_generator_node import campaign_generator_node
from content_generator_node import content_generator_node
from content_strategy_node import content_strategy_node
from trend_research_node import trend_research_node
from content_state import ContentState

logger = logging.getLogger(__name__)



NODE_BRAND_CONTEXT: str = "brand_context_node"
NODE_TREND_RESEARCH: str = "trend_research_node"
NODE_CONTENT_STRATEGY: str = "content_strategy_node"
NODE_CALENDAR_BUILDER: str = "calendar_builder_node"
NODE_CONTENT_GENERATOR: str = "content_generator_node"
NODE_CAMPAIGN_GENERATOR: str = "campaign_generator_node"
NODE_EVIDENCE_FAILURE: str = "evidence_failure_node"

# Seconds to sleep between heavy LLM nodes to avoid Groq free-tier
# TPM (tokens-per-minute) 429 rate limits. Override via env var:
#   GROQ_COOLDOWN_SECONDS=10 python main.py   (more aggressive throttle)
#   GROQ_COOLDOWN_SECONDS=0  python main.py   (paid tier — no cooldown)
GROQ_COOLDOWN_SECONDS: float = float(os.getenv("GROQ_COOLDOWN_SECONDS", "5"))


# ---------------------------------------------------------------------------
# Evidence-failure handler
# Called when any upstream node returned zero evidence. Records the failure
# in state and allows the graph to terminate gracefully without propagating
# hallucinated / ungrounded content downstream.
# ---------------------------------------------------------------------------

async def evidence_failure_node(state: ContentState) -> dict[str, Any]:
    """
    Terminal failure node.

    Inspects which evidence fields are empty/missing and appends a
    structured error entry. The graph routes here from any upstream
    node that produced no grounded evidence.

    Returns a partial state update — only touches `errors` and
    `node_execution_log`.
    """
    errors: list[dict[str, str]] = list(state.get("errors") or [])
    log: list[dict[str, Any]] = list(state.get("node_execution_log") or [])

    # Determine which node failed by inspecting evidence gaps
    failure_reason = _detect_evidence_gap(state)

    error_entry: dict[str, str] = {
        "node": NODE_EVIDENCE_FAILURE,
        "message": (
            f"Workflow halted: {failure_reason}. "
            "No content was generated downstream to prevent hallucination."
        ),
        "field": failure_reason,
    }
    errors.append(error_entry)
    logger.error("Evidence failure detected: %s", failure_reason)

    log.append(
        {
            "node": NODE_EVIDENCE_FAILURE,
            "status": "failed",
            "evidence_count": 0,
            "duration_ms": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    return {
        "errors": errors,
        "node_execution_log": log,
    }


def _detect_evidence_gap(state: ContentState) -> str:
    """
    Returns a human-readable description of the first missing evidence
    field found in state. Used to produce a meaningful error message.
    """
    checks: list[tuple[str, Any]] = [
        ("brand_context_evidence", state.get("brand_context_evidence")),
        ("trend_research_results", state.get("trend_research_results")),
        ("content_pillars", state.get("content_pillars")),
        ("content_calendar", state.get("content_calendar")),
    ]
    for field_name, value in checks:
        if not value:
            return f"'{field_name}' is empty or missing"
    return "unknown evidence gap"


# ---------------------------------------------------------------------------
# Routing guards
# Each guard is a pure function (no I/O) that inspects state and returns
# the name of the next node. LangGraph calls these after the preceding node.
# ---------------------------------------------------------------------------

def route_after_brand_context(state: ContentState) -> str:
    """
    After brand_context_node:
      - Proceed to trend research if brand_context_evidence is populated.
      - Halt with evidence_failure_node otherwise.
    """
    evidence = state.get("brand_context_evidence")
    if evidence and len(evidence) > 0:
        logger.debug(
            "brand_context_node passed evidence guard (%d sources).",
            len(evidence),
        )
        return NODE_TREND_RESEARCH
    logger.warning("brand_context_node produced no evidence. Routing to failure.")
    return NODE_EVIDENCE_FAILURE


def route_after_trend_research(state: ContentState) -> str:
    """
    After trend_research_node:
      - Proceed if trend_research_results is non-empty.
      - Halt otherwise.
    """
    results = state.get("trend_research_results")
    if results and len(results) > 0:
        logger.debug(
            "trend_research_node passed evidence guard (%d results).",
            len(results),
        )
        return NODE_CONTENT_STRATEGY
    logger.warning("trend_research_node produced no results. Routing to failure.")
    return NODE_EVIDENCE_FAILURE


def route_after_content_strategy(state: ContentState) -> str:
    """
    After content_strategy_node:
      - Proceed if content_pillars are defined with evidence.
      - Halt otherwise.
    """
    pillars = state.get("content_pillars")
    if pillars and len(pillars) > 0:
        logger.debug(
            "content_strategy_node passed evidence guard (%d pillars).",
            len(pillars),
        )
        return NODE_CALENDAR_BUILDER
    logger.warning("content_strategy_node produced no pillars. Routing to failure.")
    return NODE_EVIDENCE_FAILURE


def route_after_calendar_builder(state: ContentState) -> str:
    """
    After calendar_builder_node:
      - Proceed if content_calendar is non-empty.
      - Halt otherwise.
    """
    calendar = state.get("content_calendar")
    if calendar and len(calendar) > 0:
        logger.debug(
            "calendar_builder_node passed evidence guard (%d posts).",
            len(calendar),
        )
        return NODE_CONTENT_GENERATOR
    logger.warning("calendar_builder_node produced empty calendar. Routing to failure.")
    return NODE_EVIDENCE_FAILURE


# ---------------------------------------------------------------------------
# Graph metadata injector
# Runs before the first node to stamp the state with run-level metadata.
# This is a lightweight node — no LLM calls, no I/O.
# ---------------------------------------------------------------------------

async def _initialise_run_metadata(state: ContentState) -> dict[str, Any]:
    """
    Injects run-level metadata into state before graph execution begins.
    Assigned as the first node in the graph (between START and brand_context_node)
    so every downstream node can read a stable run_id and timestamp.
    """
    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Content Creator Agent run started | run_id=%s | brand=%s",
        run_id,
        state.get("brand_name", "unknown"),
    )

    return {
        "generation_metadata": {
            "run_id": run_id,
            "model_used": "",          # Populated by individual nodes
            "total_evidence_sources": 0,
            "generation_timestamp": timestamp,
            "posts_requested": state.get("posts_per_month", 0),
            "posts_generated": 0,      # Populated by content_generator_node
        },
        "errors": [],
        "node_execution_log": [],
    }


NODE_INIT_METADATA: str = "init_run_metadata"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_content_graph() -> Any:
    """
    Constructs, wires, and compiles the Content Creator Agent StateGraph.

    Returns
    -------
    CompiledGraph
        A compiled LangGraph graph ready for `.ainvoke()` / `.invoke()` calls.

    Node registration order
    -----------------------
    1. init_run_metadata        — stamps run_id, clears error/log lists
    2. brand_context_node       — brand profile + context evidence
    3. trend_research_node      — Tavily search + trend extraction
    4. content_strategy_node    — strategy doc + content pillars
    5. calendar_builder_node    — monthly post schedule
    6. content_generator_node   — captions / hashtags / CTAs / scripts
    7. campaign_generator_node  — campaigns + anniversary campaign
    8. evidence_failure_node    — graceful halt on evidence gaps

    Edge map
    --------
    START → init_run_metadata
    init_run_metadata → brand_context_node
    brand_context_node →(conditional)→ trend_research_node | evidence_failure_node
    trend_research_node →(conditional)→ content_strategy_node | evidence_failure_node
    content_strategy_node →(conditional)→ calendar_builder_node | evidence_failure_node
    calendar_builder_node →(conditional)→ content_generator_node | evidence_failure_node
    content_generator_node → campaign_generator_node
    campaign_generator_node → END
    evidence_failure_node → END
    """
    graph = StateGraph(ContentState)

    # ----------------------------------------------------------------
    # Register nodes
    # ----------------------------------------------------------------
    graph.add_node(NODE_INIT_METADATA,      _initialise_run_metadata)
    graph.add_node(NODE_BRAND_CONTEXT,      brand_context_node)
    graph.add_node(NODE_TREND_RESEARCH,     trend_research_node)
    graph.add_node(NODE_CONTENT_STRATEGY,   content_strategy_node)
    graph.add_node(NODE_CALENDAR_BUILDER,   calendar_builder_node)
    graph.add_node(NODE_CONTENT_GENERATOR,  content_generator_node)
    graph.add_node(NODE_CAMPAIGN_GENERATOR, campaign_generator_node)
    graph.add_node(NODE_EVIDENCE_FAILURE,   evidence_failure_node)

    # ----------------------------------------------------------------
    # Entry edges
    # ----------------------------------------------------------------
    graph.add_edge(START,             NODE_INIT_METADATA)
    graph.add_edge(NODE_INIT_METADATA, NODE_BRAND_CONTEXT)

    # ----------------------------------------------------------------
    # Conditional edges with evidence guards
    # ----------------------------------------------------------------
    graph.add_conditional_edges(
        NODE_BRAND_CONTEXT,
        route_after_brand_context,
        {
            NODE_TREND_RESEARCH:  NODE_TREND_RESEARCH,
            NODE_EVIDENCE_FAILURE: NODE_EVIDENCE_FAILURE,
        },
    )

    graph.add_conditional_edges(
        NODE_TREND_RESEARCH,
        route_after_trend_research,
        {
            NODE_CONTENT_STRATEGY: NODE_CONTENT_STRATEGY,
            NODE_EVIDENCE_FAILURE:  NODE_EVIDENCE_FAILURE,
        },
    )

    graph.add_conditional_edges(
        NODE_CONTENT_STRATEGY,
        route_after_content_strategy,
        {
            NODE_CALENDAR_BUILDER: NODE_CALENDAR_BUILDER,
            NODE_EVIDENCE_FAILURE:  NODE_EVIDENCE_FAILURE,
        },
    )

    graph.add_conditional_edges(
        NODE_CALENDAR_BUILDER,
        route_after_calendar_builder,
        {
            NODE_CONTENT_GENERATOR: NODE_CONTENT_GENERATOR,
            NODE_EVIDENCE_FAILURE:   NODE_EVIDENCE_FAILURE,
        },
    )

    # ----------------------------------------------------------------
    # Unconditional terminal edges
    # ----------------------------------------------------------------
    graph.add_edge(NODE_CONTENT_GENERATOR,  NODE_CAMPAIGN_GENERATOR)
    graph.add_edge(NODE_CAMPAIGN_GENERATOR, END)
    graph.add_edge(NODE_EVIDENCE_FAILURE,   END)

    # ----------------------------------------------------------------
    # Compile
    # ----------------------------------------------------------------
    compiled = graph.compile()
    logger.info("Content Creator Agent graph compiled successfully.")
    return compiled


# ---------------------------------------------------------------------------
# Singleton graph instance
# Built once at module import time so the agent can call run_content_graph()
# without rebuilding on every request. Thread-safe: LangGraph compiled graphs
# are stateless — all mutable data lives in the state dict, not the graph.
# ---------------------------------------------------------------------------

_content_graph = build_content_graph()


# ---------------------------------------------------------------------------
# Public async entry point
# ---------------------------------------------------------------------------

async def run_content_graph(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    foundation_date: str,
    social_platforms: list[str],
    posts_per_month: int,
) -> ContentState:
    """
    Async entry point for the Content Creator Agent workflow.

    Constructs the initial state from user-supplied inputs, invokes the
    compiled graph, and returns the fully populated ContentState.

    Parameters
    ----------
    brand_name : str
        Legal or operating name of the brand.
    industry : str
        Industry vertical (e.g. 'Specialty Coffee').
    country : str
        Country of operation.
    city : str
        City for hyper-local trend and audience context.
    foundation_date : str
        ISO date string 'YYYY-MM-DD' for brand age / anniversary logic.
    social_platforms : list[str]
        Target platforms (e.g. ['Instagram', 'TikTok', 'LinkedIn']).
    posts_per_month : int
        Total posts to generate across all platforms.

    Returns
    -------
    ContentState
        Fully populated state. Callers should always check `state['errors']`
        before consuming generated content — a non-empty list signals
        degraded or partial output.

    Raises
    ------
    ValueError
        If any required input is missing or invalid before graph invocation.
    RuntimeError
        If the graph itself raises an unhandled exception (propagated as-is).

    Example
    -------
    >>> state = await run_content_graph(
    ...     brand_name="Bloom Coffee",
    ...     industry="Specialty Coffee",
    ...     country="Egypt",
    ...     city="Cairo",
    ...     foundation_date="2019-03-15",
    ...     social_platforms=["Instagram", "TikTok"],
    ...     posts_per_month=20,
    ... )
    >>> if state.get("errors"):
    ...     print("Degraded run:", state["errors"])
    >>> posts = state.get("generated_posts", [])
    """
    _validate_inputs(
        brand_name=brand_name,
        industry=industry,
        country=country,
        city=city,
        foundation_date=foundation_date,
        social_platforms=social_platforms,
        posts_per_month=posts_per_month,
    )

    initial_state: ContentState = {
        # [IN] User-supplied fields
        "brand_name": brand_name,
        "industry": industry,
        "country": country,
        "city": city,
        "foundation_date": foundation_date,
        "social_platforms": social_platforms,
        "posts_per_month": posts_per_month,
        # All output fields initialised to None / empty
        # so nodes always receive a predictable baseline.
        "brand_profile": None,
        "brand_context_evidence": None,
        "trend_research_results": None,
        "trending_topics": None,
        "competitor_insights": None,
        "local_trends": None,
        "content_strategy": None,
        "content_pillars": None,
        "strategy_evidence_used": None,
        "content_calendar": None,
        "calendar_summary": None,
        "generated_posts": None,
        "hashtag_bank": None,
        "cta_bank": None,
        "campaign_ideas": None,
        "anniversary_campaign": None,
        "campaign_evidence_used": None,
        "errors": None,
        "node_execution_log": None,
        "generation_metadata": None,
    }

    logger.info(
        "Invoking Content Creator Agent | brand=%s | platforms=%s | posts=%d",
        brand_name,
        social_platforms,
        posts_per_month,
    )

    final_state: ContentState = await _content_graph.ainvoke(initial_state)

    _log_run_summary(final_state)
    return final_state


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_VALID_PLATFORMS: frozenset[str] = frozenset(
    {
        "Instagram",
        "TikTok",
        "LinkedIn",
        "X",
        "Facebook",
        "YouTube Shorts",
        "Pinterest",
        "Threads",
    }
)


def _validate_inputs(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    foundation_date: str,
    social_platforms: list[str],
    posts_per_month: int,
) -> None:
    """
    Validates user-supplied inputs before graph invocation.
    Raises ValueError with a descriptive message on the first violation
    found.
    """
    if not brand_name or not brand_name.strip():
        raise ValueError("'brand_name' must be a non-empty string.")

    if not industry or not industry.strip():
        raise ValueError("'industry' must be a non-empty string.")

    if not country or not country.strip():
        raise ValueError("'country' must be a non-empty string.")

    if not city or not city.strip():
        raise ValueError("'city' must be a non-empty string.")

    # Validate ISO date format
    try:
        datetime.strptime(foundation_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"'foundation_date' must be in ISO format 'YYYY-MM-DD'. "
            f"Got: '{foundation_date}'."
        )

    if not social_platforms:
        raise ValueError("'social_platforms' must contain at least one platform.")

    invalid = [p for p in social_platforms if p not in _VALID_PLATFORMS]
    if invalid:
        raise ValueError(
            f"Unrecognised platform(s): {invalid}. "
            f"Valid options: {sorted(_VALID_PLATFORMS)}."
        )

    if not isinstance(posts_per_month, int) or posts_per_month < 1:
        raise ValueError(
            f"'posts_per_month' must be a positive integer. Got: {posts_per_month}."
        )

    if posts_per_month > 120:
        raise ValueError(
            f"'posts_per_month' cannot exceed 120. Got: {posts_per_month}. "
            "Split into multiple runs if needed."
        )


# ---------------------------------------------------------------------------
# Run summary logger
# ---------------------------------------------------------------------------

def _log_run_summary(state: ContentState) -> None:
    """
    Emits a structured summary log line after the graph finishes.
    Helps ops teams quickly assess run health without parsing full state.
    """
    metadata = state.get("generation_metadata") or {}
    errors = state.get("errors") or []
    posts = state.get("generated_posts") or []
    campaigns = state.get("campaign_ideas") or []

    logger.info(
        "Content Creator Agent run complete | "
        "run_id=%s | "
        "posts_generated=%d / %d | "
        "campaigns=%d | "
        "errors=%d | "
        "evidence_sources=%d",
        metadata.get("run_id", "unknown"),
        len(posts),
        state.get("posts_per_month", 0),
        len(campaigns),
        len(errors),
        metadata.get("total_evidence_sources", 0),
    )

    if errors:
        for err in errors:
            logger.warning(
                "Run error | node=%s | field=%s | message=%s",
                err.get("node"),
                err.get("field"),
                err.get("message"),
            )