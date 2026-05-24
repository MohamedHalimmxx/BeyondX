import logging
from typing import Any, cast, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from prompts.research_prompt import (
    RESEARCH_EXTRACTOR_HUMAN_TEMPLATE,
    RESEARCH_EXTRACTOR_SYSTEM_PROMPT,
)
from state.research_state import ResearchState
from tools.search_tool import MarketSearchTool
from tools.competitor_tool import find_local_competitors
from tools.market_report_tool import MarketReportTool

logger = logging.getLogger("research_agent.nodes.research_node")


class IdeaContext(BaseModel):
    """LLM-extracted context from the business idea."""
    category: str = Field(..., description="The core business category, e.g. 'fried chicken restaurant', 'SaaS project management tool', 'online pharmacy'")
    location: Optional[str] = Field(default=None, description="The city or country mentioned in the idea. None if no location specified.")
    is_competitor_question: bool = Field(..., description="True if the question is asking about competitors, rival businesses, or market players.")
    is_market_size_question: bool = Field(..., description="True if the question is asking about market size, growth rate, CAGR, or industry forecasts.")


class DistilledInsightsOutput(BaseModel):
    findings: list[str] = Field(
        ...,
        description="High-signal metrics, concrete competitive variables, or trend factors extracted from text."
    )


async def extract_idea_context(idea: str, question: str, llm: BaseChatModel) -> IdeaContext:
    """Uses the LLM to extract location, category, and question type from the idea and question."""
    structured_llm = llm.with_structured_output(IdeaContext)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a business analyst. Extract structured context from a business idea and research question. "
                "Identify the core business category, any location mentioned, and what type of question is being asked."
            )
        },
        {
            "role": "user",
            "content": f"Business idea: {idea}\nResearch question: {question}"
        }
    ]
    return await structured_llm.ainvoke(messages)


async def research_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("Executing Research Node: Commencing data collection cycle.")

    plan = state.get("research_plan", [])
    current_idx = state.get("iteration", 0)
    idea = state.get("idea", "")

    if not plan:
        logger.warning("Empty plan received. Halting.")
        return {}

    target_question = plan[current_idx % len(plan)]
    logger.info(f"Targeting question [{current_idx % len(plan)}/{len(plan)}]: '{target_question}'")

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        raise KeyError("LLM dependency missing from graph configuration.")

    # Let the LLM extract context — no hardcoding
    context = await extract_idea_context(idea=idea, question=target_question, llm=llm)
    logger.info(f"Extracted context — category: '{context.category}', location: '{context.location}', competitor_q: {context.is_competitor_question}, market_size_q: {context.is_market_size_question}")

    if context.is_competitor_question and context.location:
        logger.info(f"Routing to Google Places: '{context.category}' in '{context.location}'")
        raw_search_dump = await find_local_competitors(
            category=context.category,
            location=context.location
        )

    elif context.is_market_size_question:
        logger.info("Routing to market report tool.")
        report_tool = MarketReportTool()
        location_str = context.location or ""
        raw_search_dump = await report_tool.search(
            query=f"{context.category} market size growth {location_str}".strip()
        )

    else:
        logger.info("Routing to general Tavily search.")
        search_tool = MarketSearchTool()
        location_str = context.location or ""
        raw_search_dump = await search_tool.run_async(
            query=f"{context.category} {location_str} {target_question}".strip()
        )

    structured_llm = llm.with_structured_output(DistilledInsightsOutput)
    messages = [
        {"role": "system", "content": RESEARCH_EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": RESEARCH_EXTRACTOR_HUMAN_TEMPLATE.format(
            idea=idea,
            question=target_question,
            raw_data=raw_search_dump
        )}
    ]

    try:
        raw_response = await structured_llm.ainvoke(messages)
        distilled = cast(DistilledInsightsOutput, raw_response)
        logger.info(f"Extracted {len(distilled.findings)} findings.")

        return {
            "gathered_data": [f"Question: {target_question}\n{raw_search_dump}"],
            "insights": distilled.findings,
            "iteration": current_idx + 1
        }

    except Exception as exc:
        logger.error(f"Research node error: {str(exc)}", exc_info=True)
        return {
            "gathered_data": [f"Question: {target_question}\n{raw_search_dump}"],
            "iteration": current_idx + 1
        }
