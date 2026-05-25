import asyncio
import logging
from typing import cast
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from pydantic import BaseModel, Field

from prompts.analyst_prompts import (
    AXES_SYSTEM_PROMPT, AXES_HUMAN_TEMPLATE,
    ENRICHMENT_EXTRACTION_SYSTEM_PROMPT, ENRICHMENT_EXTRACTION_HUMAN_TEMPLATE,
    SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_HUMAN_TEMPLATE
)
from state.analyst_state import (
    BrandAnalystOutput, CompetitorProfile, PositioningAxes
)
from tools.competitor_enricher import enrich_competitor
from config.llm_factory import get_fallback_llm

logger = logging.getLogger("research_agent.nodes.analyst_node")

MAX_COMPETITORS_TO_ENRICH = 6


class CompetitorBasic(BaseModel):
    """Basic competitor info extracted from research for enrichment."""
    name: str
    rating: float = Field(default=0.0)
    review_count: int = Field(default=0)
    location: str = Field(default="")
    category: str = Field(default="")


class CompetitorListOutput(BaseModel):
    """Structured list of competitors extracted from research report."""
    competitors: list[CompetitorBasic]
    location: str = Field(..., description="City or country where competitors operate")
    category: str = Field(..., description="The core business category")


async def extract_competitors_from_research(
    idea: str,
    research_report: str,
    llm: BaseChatModel
) -> CompetitorListOutput:
    structured_llm = llm.with_structured_output(CompetitorListOutput)
    messages = [
        {
            "role": "system",
            "content": (
                "Extract the list of competitors mentioned in this market research report. "
                "Include their names, ratings, and review counts where available. "
                "Also identify the location and business category from the context."
            )
        },
        {
            "role": "user",
            "content": f"Business idea: {idea}\n\nResearch report:\n{research_report}"
        }
    ]
    return cast(CompetitorListOutput, await structured_llm.ainvoke(messages))


async def derive_positioning_axes(
    idea: str,
    market_context: str,
    llm: BaseChatModel
) -> PositioningAxes:
    structured_llm = llm.with_structured_output(PositioningAxes)
    messages = [
        {"role": "system", "content": AXES_SYSTEM_PROMPT},
        {"role": "user", "content": AXES_HUMAN_TEMPLATE.format(
            idea=idea,
            market_context=market_context
        )}
    ]
    return cast(PositioningAxes, await structured_llm.ainvoke(messages))


async def extract_competitor_profile(
    enriched_data: dict,
    axes: PositioningAxes,
    llm: BaseChatModel
) -> CompetitorProfile:
    structured_llm = llm.with_structured_output(CompetitorProfile)
    messages = [
        {"role": "system", "content": ENRICHMENT_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": ENRICHMENT_EXTRACTION_HUMAN_TEMPLATE.format(
            name=enriched_data["name"],
            rating=enriched_data["rating"],
            review_count=enriched_data["review_count"],
            axis_1_label=axes.axis_1_label,
            axis_1_low=axes.axis_1_low,
            axis_1_high=axes.axis_1_high,
            axis_2_label=axes.axis_2_label,
            axis_2_low=axes.axis_2_low,
            axis_2_high=axes.axis_2_high,
            reviews_data=enriched_data["reviews_data"],
            online_data=enriched_data["online_data"]
        )}
    ]
    return cast(CompetitorProfile, await structured_llm.ainvoke(messages))


async def invoke_with_fallback(coro_fn, llm: BaseChatModel, *args, **kwargs):
    """Runs an LLM call with automatic fallback on rate limit."""
    try:
        return await coro_fn(*args, llm=llm, **kwargs)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Analyst Node: rate limited. Switching to fallback LLM.")
            fallback = get_fallback_llm(temperature=0.2)
            return await coro_fn(*args, llm=fallback, **kwargs)
        raise


async def score_competitor_with_fallback(
    enriched: dict,
    axes: PositioningAxes,
    llm: BaseChatModel
) -> CompetitorProfile | None:
    """
    Scores a single competitor with full fallback chain:
    Primary Groq → Fallback Groq → Gemini
    """
    # Try primary
    try:
        return await extract_competitor_profile(
            enriched_data=enriched,
            axes=axes,
            llm=llm
        )
    except RateLimitError as e:
        if "tokens per day" not in str(e) and "rate_limit_exceeded" not in str(e):
            raise

    # Try fallback (Groq key 2 or Gemini)
    logger.warning(f"Primary exhausted for {enriched['name']}. Trying fallback.")
    try:
        fallback = get_fallback_llm(temperature=0.2)
        return await extract_competitor_profile(
            enriched_data=enriched,
            axes=axes,
            llm=fallback
        )
    except RateLimitError as e:
        if "tokens per day" not in str(e) and "rate_limit_exceeded" not in str(e):
            raise

    # Both Groq keys exhausted — this should not happen with a fresh key
    logger.error(f"All keys exhausted for {enriched['name']}. Skipping.")
    return None


async def analyst_node(
    idea: str,
    research_report: str,
    insights: list[str],
    llm: BaseChatModel
) -> BrandAnalystOutput:
    """
    Full brand positioning analysis pipeline.

    Steps:
    1. Extract competitor list from research
    2. Derive positioning axes from industry context
    3. Enrich each competitor with real reviews + web data
    4. Score each competitor from evidence
    5. Synthesize white spaces, pain points, and positioning recommendation
    """
    logger.info("Executing Analyst Node: Starting full brand positioning analysis.")

    market_context = "\n".join([f"- {i}" for i in insights[:20]])

    # Step 1 — Extract competitors from research
    logger.info("Step 1: Extracting competitor list from research.")
    competitor_list = await invoke_with_fallback(
        extract_competitors_from_research,
        llm,
        idea=idea,
        research_report=research_report
    )
    logger.info(f"Found {len(competitor_list.competitors)} competitors. "
                f"Location: {competitor_list.location}, Category: {competitor_list.category}")

    # Step 2 — Derive positioning axes
    logger.info("Step 2: Deriving positioning axes.")
    axes = await invoke_with_fallback(
        derive_positioning_axes,
        llm,
        idea=idea,
        market_context=market_context
    )
    logger.info(f"Axes: '{axes.axis_1_label}' ({axes.axis_1_low}→{axes.axis_1_high}) "
                f"× '{axes.axis_2_label}' ({axes.axis_2_low}→{axes.axis_2_high})")

    # Step 3 — Enrich top competitors in parallel
    top_competitors = sorted(
        competitor_list.competitors,
        key=lambda c: c.review_count,
        reverse=True
    )[:MAX_COMPETITORS_TO_ENRICH]

    logger.info(f"Step 3: Enriching {len(top_competitors)} competitors in parallel.")
    enrichment_tasks = [
        enrich_competitor(
            name=c.name,
            rating=c.rating,
            review_count=c.review_count,
            location=competitor_list.location,
            category=competitor_list.category
        )
        for c in top_competitors
    ]
    enriched_data_list = await asyncio.gather(*enrichment_tasks, return_exceptions=True)

    valid_enrichments = [
        e for e in enriched_data_list
        if isinstance(e, dict)
    ]
    logger.info(f"Successfully enriched {len(valid_enrichments)}/{len(top_competitors)} competitors.")

    # Step 4 — Score each competitor sequentially with full fallback chain
    logger.info("Step 4: Scoring competitors from evidence.")
    profiles = []
    for enriched in valid_enrichments:
        profile = await score_competitor_with_fallback(
            enriched=enriched,
            axes=axes,
            llm=llm
        )
        if profile:
            profiles.append(profile)
            logger.info(f"Scored: {profile.name} — "
                        f"Axis1: {profile.axis_1_score}, Axis2: {profile.axis_2_score}, "
                        f"Confidence: {profile.data_confidence}")
        await asyncio.sleep(1)

    # Step 5 — Synthesize final output
    logger.info("Step 5: Synthesizing white spaces, pain points, and positioning.")

    competitor_profiles_text = "\n\n".join([
        f"**{p.name}** (Rating: {p.rating}/5, {p.review_count} reviews)\n"
        f"- {axes.axis_1_label}: {p.axis_1_score}/10 ({p.pricing_tier})\n"
        f"- {axes.axis_2_label}: {p.axis_2_score}/10 ({p.service_style})\n"
        f"- Brand personality: {p.brand_personality}\n"
        f"- Target audience: {p.target_audience}\n"
        f"- Channels: {p.distribution_channels}\n"
        f"- Strengths: {', '.join(p.top_strengths)}\n"
        f"- Weaknesses: {', '.join(p.top_weaknesses)}\n"
        f"- Evidence confidence: {p.data_confidence}\n"
        f"- Evidence: {p.evidence_summary}"
        for p in profiles
    ]) if profiles else "No competitor profiles available."

    async def run_synthesis(active_llm):
        structured = active_llm.with_structured_output(BrandAnalystOutput)
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": SYNTHESIS_HUMAN_TEMPLATE.format(
                idea=idea,
                axis_1_label=axes.axis_1_label,
                axis_1_low=axes.axis_1_low,
                axis_1_high=axes.axis_1_high,
                axis_2_label=axes.axis_2_label,
                axis_2_low=axes.axis_2_low,
                axis_2_high=axes.axis_2_high,
                competitor_profiles=competitor_profiles_text,
                market_context=market_context
            )}
        ]
        return cast(BrandAnalystOutput, await structured.ainvoke(messages))

    try:
        result = await run_synthesis(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Synthesis: rate limited. Switching to fallback.")
            fallback = get_fallback_llm(temperature=0.2)
            result = await run_synthesis(fallback)
        else:
            raise

    result.positioning_axes = axes
    result.competitors = profiles

    logger.info(
        f"Analyst Node complete. "
        f"{len(result.competitors)} competitors profiled, "
        f"{len(result.white_spaces)} white spaces identified, "
        f"{len(result.pain_points)} pain points found."
    )
    return result


async def generate_positioning_statement(
    idea: str,
    analysis: BrandAnalystOutput,
    llm: BaseChatModel
) -> "PositioningStatement":
    """
    Generates a structured positioning statement from the white space
    and pain point analysis. Bridges analyst output to strategy writer.
    """
    from state.analyst_state import PositioningStatement

    structured_llm = llm.with_structured_output(PositioningStatement)

    white_space = analysis.white_spaces[0] if analysis.white_spaces else None
    pain_point = analysis.pain_points[0] if analysis.pain_points else None
    top_competitor = analysis.competitors[0] if analysis.competitors else None

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior brand strategist. "
                "Write a positioning statement using the classic format: "
                "'For [audience] who [need], [Brand] is the [category] that [differentiator]. "
                "Unlike [competitor], we [proof point].' "
                "Every field must be specific and derived from the analysis data provided. "
                "No generic statements. The full_statement field must be the complete sentence."
            )
        },
        {
            "role": "user",
            "content": (
                f"Business idea: {idea}\n\n"
                f"Target audience: {analysis.target_audience_summary}\n"
                f"White space: {white_space.description if white_space else 'Not identified'}\n"
                f"Primary pain point: {pain_point.description if pain_point else 'Not identified'}\n"
                f"Main competitor to differentiate from: {top_competitor.name if top_competitor else 'existing players'}\n"
                f"Competitive advantage: {analysis.competitive_advantage}\n\n"
                "Generate the positioning statement:"
            )
        }
    ]

    try:
        return cast(PositioningStatement, await structured_llm.ainvoke(messages))
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            fallback = get_fallback_llm(temperature=0.2)
            structured_fallback = fallback.with_structured_output(PositioningStatement)
            return cast(PositioningStatement, await structured_fallback.ainvoke(messages))
        raise
