from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from content_graph import run_content_graph
from content_state import ContentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid platform registry
# Single source of truth — matches graph/content_graph.py _VALID_PLATFORMS
# ---------------------------------------------------------------------------

VALID_PLATFORMS: frozenset[str] = frozenset(
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

MAX_POSTS_PER_MONTH: int = 120
MIN_POSTS_PER_MONTH: int = 1


# ---------------------------------------------------------------------------
# Output model
# Pydantic v2 model — clean, serialisable, typed output contract.
# Hides all LangGraph internals from the caller.
# ---------------------------------------------------------------------------

class ContentCreatorOutput(BaseModel):
    """
    Structured output returned by ContentCreatorAgent.run().

    Every field is Optional to accommodate partial runs where some
    nodes succeeded and others failed. Callers must always check
    `status` and `errors` before consuming generated content.
    """

    # ── Run identity ──────────────────────────────────────────────────────
    run_id: str = Field(
        description="UUID identifying this workflow run."
    )
    status: str = Field(
        description=(
            "'success' — all nodes completed without errors. "
            "'partial' — some nodes completed with non-fatal errors. "
            "'failed' — one or more critical nodes failed."
        )
    )
    generation_timestamp: str = Field(
        description="ISO datetime when this run completed."
    )

    # ── Brand intelligence ────────────────────────────────────────────────
    brand_profile: Optional[dict[str, Any]] = Field(
        default=None,
        description="Structured brand context profile from brand_context_node.",
    )

    # ── Content strategy ──────────────────────────────────────────────────
    content_strategy: Optional[dict[str, Any]] = Field(
        default=None,
        description="Full strategy document from content_strategy_node.",
    )
    # TypedDicts (ContentPillar, PostEntry, CampaignIdea, AnniversaryCampaign)
    # are plain dicts at runtime. We use list[dict[str, Any]] here to keep
    # Pydantic v2 happy on Python < 3.12 — values are still fully typed
    # in the nodes via the TypedDict definitions in content_state.py.
    content_pillars: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Validated content pillars with evidence justification.",
    )

    # ── Calendar and generated content ───────────────────────────────────
    content_calendar: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Monthly post schedule skeleton from calendar_builder_node. "
            "Captions and scripts are empty — see generated_posts."
        ),
    )
    generated_posts: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Fully populated posts with captions, hashtags, CTAs, "
            "and reel scripts from content_generator_node."
        ),
    )

    # ── Campaigns ────────────────────────────────────────────────────────
    campaign_ideas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Standalone campaign concepts from campaign_generator_node.",
    )
    anniversary_campaign: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Milestone anniversary campaign if the brand's next anniversary "
            "falls within the campaign window. None otherwise."
        ),
    )

    # ── Asset banks ───────────────────────────────────────────────────────
    hashtag_bank: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Hashtag library organised by platform and pillar. "
            "Shape: { platform: { pillar: [#tag, ...] } }"
        ),
    )
    cta_bank: list[str] = Field(
        default_factory=list,
        description="Deduplicated reusable CTA library.",
    )

    # ── Evidence audit ────────────────────────────────────────────────────
    trending_topics: list[str] = Field(
        default_factory=list,
        description="Validated trending topic labels from trend_research_node.",
    )
    local_trends: list[str] = Field(
        default_factory=list,
        description="City/country-specific trend signals.",
    )

    # ── Observability ─────────────────────────────────────────────────────
    errors: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Non-fatal errors collected during the run. "
            "Non-empty list signals degraded output."
        ),
    )
    node_execution_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered execution trace for debugging.",
    )
    generation_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Run statistics: model used, evidence count, post counts.",
    )

    # ── Run summary ───────────────────────────────────────────────────────
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "High-level run summary for quick caller inspection. "
            "Shape: { posts_generated, campaigns_generated, "
            "has_anniversary_campaign, evidence_sources_used, "
            "nodes_succeeded, nodes_failed, has_errors }"
        ),
    )

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Input model
# Pydantic v2 model for input validation before graph invocation.
# ---------------------------------------------------------------------------

class ContentCreatorInput(BaseModel):
    """
    Validated input model for ContentCreatorAgent.run().

    All validation happens here — the graph receives only clean,
    validated inputs.
    """

    brand_name: str = Field(
        min_length=1,
        max_length=200,
        description="Legal or operating name of the brand.",
    )
    industry: str = Field(
        min_length=1,
        max_length=200,
        description="Industry vertical (e.g. 'Specialty Coffee').",
    )
    country: str = Field(
        min_length=1,
        max_length=100,
        description="Country of operation.",
    )
    city: str = Field(
        min_length=1,
        max_length=100,
        description="City for hyper-local context.",
    )
    foundation_date: str = Field(
        description="Brand foundation date in ISO format 'YYYY-MM-DD'.",
    )
    social_platforms: list[str] = Field(
        min_length=1,
        description="Target social platforms.",
    )
    posts_per_month: int = Field(
        ge=MIN_POSTS_PER_MONTH,
        le=MAX_POSTS_PER_MONTH,
        description=f"Total posts to generate ({MIN_POSTS_PER_MONTH}–{MAX_POSTS_PER_MONTH}).",
    )

    @field_validator("foundation_date")
    @classmethod
    def validate_foundation_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"foundation_date must be in ISO format 'YYYY-MM-DD'. Got: '{v}'."
            )
        return v

    @field_validator("social_platforms")
    @classmethod
    def validate_platforms(cls, v: list[str]) -> list[str]:
        invalid = [p for p in v if p not in VALID_PLATFORMS]
        if invalid:
            raise ValueError(
                f"Unrecognised platform(s): {invalid}. "
                f"Valid options: {sorted(VALID_PLATFORMS)}."
            )
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for platform in v:
            if platform not in seen:
                seen.add(platform)
                deduped.append(platform)
        return deduped

    @field_validator("brand_name", "industry", "country", "city")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be an empty or whitespace-only string.")
        return v.strip()


# ---------------------------------------------------------------------------
# Run status resolver
# ---------------------------------------------------------------------------

def _resolve_run_status(state: ContentState) -> str:
    """
    Determines the overall run status from the final ContentState.

    Status hierarchy:
      "failed"  — any node logged 'failed' status, or no posts generated
      "partial" — any node logged 'partial' status, or errors present
      "success" — all nodes succeeded with no errors

    Parameters
    ----------
    state : ContentState
        Fully populated final state after graph execution.

    Returns
    -------
    str
        One of: 'success', 'partial', 'failed'
    """
    errors = state.get("errors") or []
    log = state.get("node_execution_log") or []
    generated_posts = state.get("generated_posts") or []
    posts_per_month = state.get("posts_per_month") or 0

    # Check for any failed nodes
    node_statuses = [entry.get("status", "") for entry in log]
    if "failed" in node_statuses:
        return "failed"

    # No posts generated at all — failed
    if posts_per_month > 0 and len(generated_posts) == 0:
        return "failed"

    # Partial nodes or errors present
    if "partial" in node_statuses or errors:
        return "partial"

    return "success"


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_run_summary(
    state: ContentState,
    status: str,
) -> dict[str, Any]:
    """
    Builds the high-level run summary for quick caller inspection.

    Parameters
    ----------
    state : ContentState
        Final state after graph execution.
    status : str
        Resolved run status.

    Returns
    -------
    dict[str, Any]
        Summary dict attached to ContentCreatorOutput.summary.
    """
    log = state.get("node_execution_log") or []
    metadata = state.get("generation_metadata") or {}
    errors = state.get("errors") or []

    nodes_succeeded = sum(
        1 for e in log if e.get("status") == "success"
    )
    nodes_partial = sum(
        1 for e in log if e.get("status") == "partial"
    )
    nodes_failed = sum(
        1 for e in log if e.get("status") == "failed"
    )

    generated_posts = state.get("generated_posts") or []
    campaign_ideas = state.get("campaign_ideas") or []
    anniversary = state.get("anniversary_campaign")

    return {
        "status": status,
        "posts_requested": state.get("posts_per_month", 0),
        "posts_generated": len(generated_posts),
        "campaigns_generated": len(campaign_ideas),
        "has_anniversary_campaign": anniversary is not None,
        "evidence_sources_used": metadata.get(
            "total_evidence_sources", 0
        ),
        "nodes_succeeded": nodes_succeeded,
        "nodes_partial": nodes_partial,
        "nodes_failed": nodes_failed,
        "has_errors": len(errors) > 0,
        "error_count": len(errors),
        "total_duration_ms": sum(
            e.get("duration_ms", 0) for e in log
        ),
        "model_used": metadata.get("model_used", "unknown"),
    }


# ---------------------------------------------------------------------------
# Output assembler
# ---------------------------------------------------------------------------

def _assemble_output(
    state: ContentState,
    run_id: str,
) -> ContentCreatorOutput:
    """
    Assembles the final ContentCreatorOutput from the completed
    ContentState.

    Maps every state field to the appropriate output model field.
    Handles None values gracefully — every output field has a safe
    default.

    Parameters
    ----------
    state : ContentState
        Fully populated final state.
    run_id : str
        Run UUID from generation_metadata.

    Returns
    -------
    ContentCreatorOutput
        Fully populated output model.
    """
    status = _resolve_run_status(state)
    summary = _build_run_summary(state, status)
    metadata = state.get("generation_metadata") or {}

    return ContentCreatorOutput(
        # Run identity
        run_id=run_id,
        status=status,
        generation_timestamp=datetime.now(timezone.utc).isoformat(),

        # Brand intelligence
        brand_profile=state.get("brand_profile"),

        # Content strategy
        content_strategy=state.get("content_strategy"),
        content_pillars=list(state.get("content_pillars") or []),

        # Calendar and generated content
        content_calendar=list(state.get("content_calendar") or []),
        generated_posts=list(state.get("generated_posts") or []),

        # Campaigns
        campaign_ideas=list(state.get("campaign_ideas") or []),
        anniversary_campaign=state.get("anniversary_campaign"),

        # Asset banks
        hashtag_bank=dict(state.get("hashtag_bank") or {}),
        cta_bank=list(state.get("cta_bank") or []),

        # Evidence audit
        trending_topics=list(state.get("trending_topics") or []),
        local_trends=list(state.get("local_trends") or []),

        # Observability
        errors=list(state.get("errors") or []),
        node_execution_log=list(state.get("node_execution_log") or []),
        generation_metadata=metadata,

        # Run summary
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Content Creator Agent
# ---------------------------------------------------------------------------

class ContentCreatorAgent:
    """
    Content Creator Agent — public interface for the workflow.

    Usage
    -----
    >>> agent = ContentCreatorAgent()
    >>> output = await agent.run(
    ...     brand_name="Bloom Coffee",
    ...     industry="Specialty Coffee",
    ...     country="Egypt",
    ...     city="Cairo",
    ...     foundation_date="2019-03-15",
    ...     social_platforms=["Instagram", "TikTok"],
    ...     posts_per_month=20,
    ... )
    >>> print(output.status)
    'success'
    >>> print(len(output.generated_posts))
    20

    FastAPI integration
    -------------------
    >>> @router.post("/content-creator")
    ... async def create_content(request: ContentCreatorRequest):
    ...     agent = ContentCreatorAgent()
    ...     output = await agent.run(**request.model_dump())
    ...     return output.model_dump()

    Error handling
    --------------
    - `ValueError` is raised for invalid inputs (before graph runs).
    - `RuntimeError` is raised for unrecoverable graph failures.
    - Non-fatal failures are captured in output.errors and reflected
      in output.status ('partial' or 'failed').
    - Always check output.status before consuming generated content.
    """

    def __init__(self) -> None:
        self._log = logging.getLogger(self.__class__.__name__)

    async def run(
        self,
        brand_name: str,
        industry: str,
        country: str,
        city: str,
        foundation_date: str,
        social_platforms: list[str],
        posts_per_month: int,
    ) -> ContentCreatorOutput:
        """
        Runs the full Content Creator Agent workflow.

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
            ISO date string 'YYYY-MM-DD'.
        social_platforms : list[str]
            Target platforms. Valid values: Instagram, TikTok, LinkedIn,
            X, Facebook, YouTube Shorts, Pinterest, Threads.
        posts_per_month : int
            Total posts to generate across all platforms (1–120).

        Returns
        -------
        ContentCreatorOutput
            Fully populated output model. Always check .status and
            .errors before consuming generated content.

        Raises
        ------
        ValueError
            If any input fails validation.
        RuntimeError
            If the graph encounters an unrecoverable failure.
        """
        start_time = datetime.now(timezone.utc)

        # ------------------------------------------------------------
        # Step 1: Validate inputs via Pydantic model
        # ------------------------------------------------------------
        try:
            validated_input = ContentCreatorInput(
                brand_name=brand_name,
                industry=industry,
                country=country,
                city=city,
                foundation_date=foundation_date,
                social_platforms=social_platforms,
                posts_per_month=posts_per_month,
            )
        except Exception as exc:
            self._log.error(
                "Input validation failed | brand='%s' | error=%s",
                brand_name,
                str(exc),
            )
            raise ValueError(f"Input validation failed: {str(exc)}") from exc

        self._log.info(
            "ContentCreatorAgent.run() started | brand='%s' | "
            "industry='%s' | city='%s, %s' | platforms=%s | posts=%d",
            validated_input.brand_name,
            validated_input.industry,
            validated_input.city,
            validated_input.country,
            validated_input.social_platforms,
            validated_input.posts_per_month,
        )

        # ------------------------------------------------------------
        # Step 2: Invoke the graph
        # ------------------------------------------------------------
        try:
            final_state: ContentState = await run_content_graph(
                brand_name=validated_input.brand_name,
                industry=validated_input.industry,
                country=validated_input.country,
                city=validated_input.city,
                foundation_date=validated_input.foundation_date,
                social_platforms=validated_input.social_platforms,
                posts_per_month=validated_input.posts_per_month,
            )
        except ValueError as exc:
            # Graph-level input validation (redundant but safe)
            self._log.error(
                "Graph invocation error | brand='%s' | error=%s",
                validated_input.brand_name,
                str(exc),
            )
            raise
        except Exception as exc:
            self._log.exception(
                "Unrecoverable graph failure | brand='%s' | error=%s",
                validated_input.brand_name,
                str(exc),
            )
            raise RuntimeError(
                f"Content Creator Agent encountered an unrecoverable "
                f"error: {str(exc)}"
            ) from exc

        # ------------------------------------------------------------
        # Step 3: Assemble structured output
        # ------------------------------------------------------------
        run_id = (
            (final_state.get("generation_metadata") or {})
            .get("run_id", str(uuid.uuid4()))
        )

        output = _assemble_output(
            state=final_state,
            run_id=run_id,
        )

        # ------------------------------------------------------------
        # Step 4: Log run completion
        # ------------------------------------------------------------
        elapsed_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        self._log.info(
            "ContentCreatorAgent.run() complete | "
            "run_id=%s | brand='%s' | status=%s | "
            "posts=%d/%d | campaigns=%d | "
            "anniversary=%s | errors=%d | elapsed_ms=%d",
            output.run_id,
            validated_input.brand_name,
            output.status,
            len(output.generated_posts),
            validated_input.posts_per_month,
            len(output.campaign_ideas),
            "YES" if output.anniversary_campaign else "NO",
            len(output.errors),
            elapsed_ms,
        )

        if output.errors:
            self._log.warning(
                "Run completed with %d error(s) | run_id=%s | brand='%s'",
                len(output.errors),
                output.run_id,
                validated_input.brand_name,
            )
            for err in output.errors:
                self._log.warning(
                    "  [%s] %s | field=%s",
                    err.get("node", "?"),
                    err.get("message", "?"),
                    err.get("field", "?"),
                )

        return output

    async def run_from_dict(
        self,
        params: dict[str, Any],
    ) -> ContentCreatorOutput:
        """
        Convenience method — accepts a dict of parameters instead of
        keyword arguments. Useful for FastAPI request models and
        task queue payloads.

        Parameters
        ----------
        params : dict
            Must contain all required keys:
            brand_name, industry, country, city, foundation_date,
            social_platforms, posts_per_month.

        Returns
        -------
        ContentCreatorOutput

        Raises
        ------
        KeyError
            If a required key is missing from params.
        ValueError
            If any value fails validation.
        """
        required_keys = {
            "brand_name",
            "industry",
            "country",
            "city",
            "foundation_date",
            "social_platforms",
            "posts_per_month",
        }
        missing = required_keys - set(params.keys())
        if missing:
            raise KeyError(
                f"Missing required parameter(s): {sorted(missing)}"
            )

        return await self.run(
            brand_name=params["brand_name"],
            industry=params["industry"],
            country=params["country"],
            city=params["city"],
            foundation_date=params["foundation_date"],
            social_platforms=params["social_platforms"],
            posts_per_month=params["posts_per_month"],
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# For callers who prefer a functional interface over instantiation.
# ---------------------------------------------------------------------------

async def run_content_creator(
    brand_name: str,
    industry: str,
    country: str,
    city: str,
    foundation_date: str,
    social_platforms: list[str],
    posts_per_month: int,
) -> ContentCreatorOutput:
    """
    Module-level convenience function for the Content Creator Agent.

    Equivalent to ContentCreatorAgent().run(...).
    Prefer this for simple, one-shot invocations.
    Prefer ContentCreatorAgent().run() when you need instance-level
    configuration or dependency injection.

    Parameters
    ----------
    See ContentCreatorAgent.run() for full parameter documentation.

    Returns
    -------
    ContentCreatorOutput

    Example
    -------
    >>> from agents.content_creator_agent import run_content_creator
    >>> output = await run_content_creator(
    ...     brand_name="Bloom Coffee",
    ...     industry="Specialty Coffee",
    ...     country="Egypt",
    ...     city="Cairo",
    ...     foundation_date="2019-03-15",
    ...     social_platforms=["Instagram", "TikTok"],
    ...     posts_per_month=20,
    ... )
    """
    agent = ContentCreatorAgent()
    return await agent.run(
        brand_name=brand_name,
        industry=industry,
        country=country,
        city=city,
        foundation_date=foundation_date,
        social_platforms=social_platforms,
        posts_per_month=posts_per_month,
    )