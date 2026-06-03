"""Brand Analyst Node — competitive positioning analysis."""

import asyncio
import logging
from typing import cast
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from prompts.analyst_prompts import (
    AXES_SYSTEM_PROMPT, AXES_HUMAN_TEMPLATE,
    ENRICHMENT_EXTRACTION_SYSTEM_PROMPT, ENRICHMENT_EXTRACTION_HUMAN_TEMPLATE,
    SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_HUMAN_TEMPLATE,
)
from state.analyst_state import BrandAnalystOutput, CompetitorProfile, PositioningAxes, PositioningStatement
from tools.competitor_enricher import enrich_competitor
from utils.llm_utils import invoke_with_fallback

logger = logging.getLogger("research_agent.nodes.analyst_node")

MAX_COMPETITORS_TO_ENRICH = 6

_DIGITAL_CATEGORIES = {
    "saas", "software", "app", "platform", "digital", "online",
    "healthcare", "edtech", "fintech", "marketplace",
}


def _is_physical(category: str) -> bool:
    """Determine if competitors are physical businesses needing Places lookup."""
    return not any(kw in category.lower() for kw in _DIGITAL_CATEGORIES)


class CompetitorBasic(BaseModel):
    name: str
    rating: float = Field(default=0.0)
    review_count: int = Field(default=0)
    location: str = Field(default="")
    category: str = Field(default="")

    class Config:
        extra = "ignore"


class CompetitorListOutput(BaseModel):
    competitors: list[CompetitorBasic]
    location: str
    category: str

    class Config:
        extra = "ignore"


async def _extract_competitors(llm, idea: str, research_report: str) -> CompetitorListOutput:
    structured = llm.with_structured_output(CompetitorListOutput)
    messages = [
        {
            "role": "system",
            "content": (
                "Extract the list of competitors mentioned in this market research report. "
                "Include their names, ratings, and review counts where available. "
                "Also identify the location and business category from the context."
            ),
        },
        {"role": "user", "content": f"Business idea: {idea}\n\nResearch report:\n{research_report}"},
    ]
    return cast(CompetitorListOutput, await structured.ainvoke(messages))


async def _derive_axes(llm, idea: str, market_context: str) -> PositioningAxes:
    structured = llm.with_structured_output(PositioningAxes)
    messages = [
        {"role": "system", "content": AXES_SYSTEM_PROMPT},
        {"role": "user", "content": AXES_HUMAN_TEMPLATE.format(idea=idea, market_context=market_context)},
    ]
    return cast(PositioningAxes, await structured.ainvoke(messages))


async def _score_competitor(llm, enriched_data: dict, axes: PositioningAxes) -> CompetitorProfile:
    structured = llm.with_structured_output(CompetitorProfile)
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
            online_data=enriched_data["online_data"],
            data_note=enriched_data.get("data_note", ""),
        )},
    ]
    return cast(CompetitorProfile, await structured.ainvoke(messages))


async def _synthesize(llm, idea: str, axes: PositioningAxes,
                      competitor_profiles_text: str, market_context: str) -> BrandAnalystOutput:
    structured = llm.with_structured_output(BrandAnalystOutput)
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
            market_context=market_context,
        )},
    ]
    return cast(BrandAnalystOutput, await structured.ainvoke(messages))


async def _generate_positioning(llm, idea: str, analysis: BrandAnalystOutput) -> PositioningStatement:
    white_space = analysis.white_spaces[0] if analysis.white_spaces else None
    pain_point = analysis.pain_points[0] if analysis.pain_points else None
    top_competitor = analysis.competitors[0] if analysis.competitors else None

    structured = llm.with_structured_output(PositioningStatement)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior brand strategist. "
                "Write a positioning statement: "
                "'For [audience] who [need], [Brand] is the [category] that [differentiator]. "
                "Unlike [competitor], we [proof point].' "
                "Every field must be specific. The full_statement field must be the complete sentence."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Business idea: {idea}\n\n"
                f"Target audience: {analysis.target_audience_summary}\n"
                f"White space: {white_space.description if white_space else 'Not identified'}\n"
                f"Primary pain point: {pain_point.description if pain_point else 'Not identified'}\n"
                f"Main competitor: {top_competitor.name if top_competitor else 'existing players'}\n"
                f"Competitive advantage: {analysis.competitive_advantage}\n\n"
                "Generate the positioning statement:"
            ),
        },
    ]
    return cast(PositioningStatement, await structured.ainvoke(messages))


async def analyst_node(
    idea: str,
    research_report: str,
    insights: list[str],
    llm: BaseChatModel,
) -> BrandAnalystOutput:
    logger.info("Executing Analyst Node: Starting full brand positioning analysis.")

    market_context = "\n".join([f"- {i}" for i in insights[:20]])

    logger.info("Step 1: Extracting competitor list from research.")
    competitor_list = await invoke_with_fallback(_extract_competitors, llm,
                                                 idea=idea, research_report=research_report)
    logger.info(f"Found {len(competitor_list.competitors)} competitors. "
                f"Location: {competitor_list.location}, Category: {competitor_list.category}")

    logger.info("Step 2: Deriving positioning axes.")
    axes = await invoke_with_fallback(_derive_axes, llm,
                                      idea=idea, market_context=market_context)
    logger.info(f"Axes: '{axes.axis_1_label}' ({axes.axis_1_low}→{axes.axis_1_high}) "
                f"× '{axes.axis_2_label}' ({axes.axis_2_low}→{axes.axis_2_high})")

    has_physical = _is_physical(competitor_list.category)

    top_competitors = sorted(
        competitor_list.competitors, key=lambda c: c.review_count, reverse=True
    )[:MAX_COMPETITORS_TO_ENRICH]

    logger.info(f"Step 3: Enriching {len(top_competitors)} competitors in parallel.")
    enrichment_tasks = [
        enrich_competitor(
            name=c.name,
            rating=c.rating,
            review_count=c.review_count,
            location=competitor_list.location,
            category=competitor_list.category,
            has_physical_location=has_physical,
        )
        for c in top_competitors
    ]
    enriched_data_list = await asyncio.gather(*enrichment_tasks, return_exceptions=True)
    valid_enrichments = [e for e in enriched_data_list if isinstance(e, dict)]
    logger.info(f"Successfully enriched {len(valid_enrichments)}/{len(top_competitors)} competitors.")

    logger.info("Step 4: Scoring competitors from evidence.")
    profiles = []
    for enriched in valid_enrichments:
        try:
            profile = await invoke_with_fallback(_score_competitor, llm,
                                                 enriched_data=enriched, axes=axes)
            if profile:
                profiles.append(profile)
                logger.info(f"Scored: {profile.name} — "
                            f"Axis1: {profile.axis_1_score}, Axis2: {profile.axis_2_score}, "
                            f"Confidence: {profile.data_confidence}")
        except Exception as err:
            logger.error(f"Failed to score {enriched.get('name', '?')}: {err}")

    logger.info("Step 5: Synthesizing white spaces, pain points, and positioning.")
    competitor_profiles_text = "\n\n".join([
        f"**{p.name}** ({'Rating: ' + str(p.rating) + '/5, ' + str(p.review_count) + ' reviews' if p.rating is not None else 'No Google rating — web data only'})\n"
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

    result = await invoke_with_fallback(_synthesize, llm,
                                        idea=idea, axes=axes,
                                        competitor_profiles_text=competitor_profiles_text,
                                        market_context=market_context)
    result.positioning_axes = axes
    result.competitors = profiles

    logger.info(f"Analyst Node complete. {len(result.competitors)} competitors profiled, "
                f"{len(result.white_spaces)} white spaces identified, "
                f"{len(result.pain_points)} pain points found.")
    return result


async def generate_positioning_statement(
    idea: str,
    analysis: BrandAnalystOutput,
    llm: BaseChatModel,
) -> PositioningStatement:
    return await invoke_with_fallback(_generate_positioning, llm,
                                      idea=idea, analysis=analysis)