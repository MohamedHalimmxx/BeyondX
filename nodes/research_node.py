import logging
from typing import Any, cast, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio

from prompts.research_prompt import (
    RESEARCH_EXTRACTOR_HUMAN_TEMPLATE,
    RESEARCH_EXTRACTOR_SYSTEM_PROMPT,
)
from state.research_state import ResearchState
from tools.search_tool import MarketSearchTool
from tools.competitor_tool import find_local_competitors
from tools.market_report_tool import MarketReportTool
from config.llm_factory import get_fallback_llm, get_primary_llm

logger = logging.getLogger("research_agent.nodes.research_node")


class IdeaContext(BaseModel):
    category: str = Field(..., description="The core business category")
    location: Optional[str] = Field(default=None, description="City or country only if explicitly mentioned. Never invent.")
    is_competitor_question: bool = Field(..., description="True if asking about competitors or market players.")
    is_market_size_question: bool = Field(..., description="True if asking about market size, growth, CAGR.")


class DistilledInsightsOutput(BaseModel):
    findings: list[str] = Field(..., description="High-signal metrics, competitive variables, or trend factors.")


ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers are currently rate-limited or overloaded.\n"
    "   (Groq key 1, Groq key 2, Cerebras)\n"
    "   Please wait a few minutes and run again.\n"
)


async def _try_with_cerebras(coro_fn, *args, **kwargs):
    """Try a coroutine with Cerebras, retrying up to 3 times on queue errors."""
    from config.llm_factory import get_cerebras_llm
    cerebras = get_cerebras_llm()
    for attempt in range(3):
        try:
            return await coro_fn(cerebras, *args, **kwargs)
        except CerebrasRateLimitError:
            wait = (attempt + 1) * 15
            logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
            await asyncio.sleep(wait)
    raise RuntimeError(ALL_EXHAUSTED_MSG)


async def extract_idea_context(idea: str, question: str) -> IdeaContext:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a business analyst. Extract structured context from a business idea and research question. "
                "For location: extract the city or country only if explicitly mentioned. "
                "If no location is mentioned, set location to null — never invent a location."
            )
        },
        {
            "role": "user",
            "content": f"Business idea: {idea}\nResearch question: {question}"
        }
    ]

    async def run(active_llm):
        structured = active_llm.with_structured_output(IdeaContext)
        return await structured.ainvoke(messages)

    llm = get_primary_llm()
    try:
        return await run(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Context extraction: primary LLM rate limited. Switching to fallback.")
            try:
                fallback = get_fallback_llm()
                return await run(fallback)
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Context extraction: both Groq keys exhausted. Switching to Cerebras.")
                    return await _try_with_cerebras(run)
                raise
        raise


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

    context = await extract_idea_context(idea=idea, question=target_question)
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

    messages = [
        {"role": "system", "content": RESEARCH_EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": RESEARCH_EXTRACTOR_HUMAN_TEMPLATE.format(
            idea=idea,
            question=target_question,
            raw_data=raw_search_dump
        )}
    ]

    async def invoke_extraction(active_llm):
        structured = active_llm.with_structured_output(DistilledInsightsOutput)
        return cast(DistilledInsightsOutput, await structured.ainvoke(messages))

    try:
        distilled = await invoke_extraction(llm)
        logger.info(f"Extracted {len(distilled.findings)} findings.")
        return {
            "gathered_data": [f"Question: {target_question}\n{raw_search_dump}"],
            "insights": distilled.findings,
            "iteration": current_idx + 1
        }

    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Research extraction: primary LLM rate limited. Switching to fallback.")
            try:
                fallback = get_fallback_llm()
                distilled = await invoke_extraction(fallback)
                logger.info(f"Extracted {len(distilled.findings)} findings via fallback.")
                return {
                    "gathered_data": [f"Question: {target_question}\n{raw_search_dump}"],
                    "insights": distilled.findings,
                    "iteration": current_idx + 1
                }
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Research extraction: both Groq keys exhausted. Switching to Cerebras.")
                    distilled = await _try_with_cerebras(invoke_extraction)
                    logger.info(f"Extracted {len(distilled.findings)} findings via Cerebras.")
                    return {
                        "gathered_data": [f"Question: {target_question}\n{raw_search_dump}"],
                        "insights": distilled.findings,
                        "iteration": current_idx + 1
                    }
                raise
        raise

    except Exception as exc:
        logger.error(f"Research node error: {str(exc)}", exc_info=True)
        raise