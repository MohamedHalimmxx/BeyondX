import logging
from typing import Any, cast, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, validator
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
    has_physical_location: bool = Field(..., description="True if this business operates from a physical location customers visit (restaurant, gym, clinic, store). False if it is a digital product, app, platform, or online service.")
    search_query: str = Field(..., description=(
        "The optimal web search query to find relevant competitors or market data for this specific question. "
        "Think carefully: what search query would a researcher actually type to find LOCAL or REGIONAL results "
        "rather than global ones? If the business is local, include local language terms, local brand names, "
        "or qualifiers like 'local', 'Arab', 'Egyptian', 'alternative to X in Y' that surface local results. "
        "The query must be specific enough to avoid global SEO dominance by international brands."
    ))

    @validator('is_competitor_question', 'is_market_size_question', 'has_physical_location', pre=True)
    def coerce_bool(cls, v):
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes')
        return v


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
    import json
    messages = [
        {
            "role": "system",
            "content": (
                "You are a business analyst. Extract structured context from a business idea and research question. "
                "Return ONLY a valid JSON object with these exact fields:\n"
                '{"category": string, "location": string or null, '
                '"is_competitor_question": true or false, '
                '"is_market_size_question": true or false, '
                '"has_physical_location": true or false, '
                '"search_query": string}\n'
                "For location: extract city/country only if explicitly mentioned, else null.\n"
                "For has_physical_location: true only if customers physically visit "
                "(restaurant, gym, clinic, store). False for any app, platform, or online service.\n"
                "For search_query: write a query that finds LOCAL/REGIONAL results, "
                "not global SEO-dominant brands. Include local language terms if relevant.\n"
                "Return ONLY the JSON. No explanation, no markdown."
            )
        },
        {
            "role": "user",
            "content": f"Business idea: {idea}\nResearch question: {question}"
        }
    ]

    async def run(active_llm):
        response = await active_llm.ainvoke(messages)
        raw = response.content.replace("```json", "").replace("```", "").strip()
        # Find the first { and last } to extract just the JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in response: {raw[:100]}")
        raw = raw[start:end]
        data = json.loads(raw)
        return IdeaContext(**data)

    llm = get_primary_llm()
    try:
        return await run(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Context extraction: primary LLM rate limited. Switching to fallback.")
            try:
                return await run(get_fallback_llm())
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
    logger.info(
        f"Extracted context — category: '{context.category}', location: '{context.location}', "
        f"competitor_q: {context.is_competitor_question}, market_size_q: {context.is_market_size_question}, "
        f"physical: {context.has_physical_location}"
    )

    if context.is_competitor_question and context.location:
        if context.has_physical_location:
            logger.info(f"Routing to Google Places: '{context.category}' in '{context.location}'")
            raw_search_dump = await find_local_competitors(
                category=context.category,
                location=context.location
            )
        else:
            logger.info(f"Routing to Tavily web search with LLM-generated query: '{context.search_query}'")
            search_tool = MarketSearchTool()
            raw_search_dump = await search_tool.run_async(query=context.search_query)

    elif context.is_market_size_question:
        logger.info(f"Routing to market report tool with LLM-generated query: '{context.search_query}'")
        report_tool = MarketReportTool()
        raw_search_dump = await report_tool.search(query=context.search_query)
    else:
        logger.info(f"Routing to general Tavily search with LLM-generated query: '{context.search_query}'")
        search_tool = MarketSearchTool()
        raw_search_dump = await search_tool.run_async(query=context.search_query)

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