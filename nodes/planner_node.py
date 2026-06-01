import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio

from prompts.research_prompt import PLANNER_HUMAN_TEMPLATE, PLANNER_SYSTEM_PROMPT
from state.research_state import ResearchState

logger = logging.getLogger("research_agent.nodes.planner_node")

ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers are currently rate-limited or overloaded.\n"
    "   (Groq key 1, Groq key 2, Cerebras)\n"
    "   Please wait a few minutes and run again.\n"
)


class StructuredPlanOutput(BaseModel):
    questions: list[str] = Field(
        ...,
        description="A list of explicit, targeted research questions across market, competitor, audience, pricing, and trend vectors."
    )


async def planner_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("Executing Planner Node: Processing business velocity alignment.")

    idea = state.get("idea", "").strip()
    if not idea:
        logger.warning("Planner Node received an empty business idea string.")
        return {"research_plan": []}

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        raise KeyError("Critical dependency missing: 'llm' must be injected via runtime configuration.")

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": PLANNER_HUMAN_TEMPLATE.format(idea=idea)}
    ]

    async def run_planner(active_llm):
        structured_llm = active_llm.with_structured_output(StructuredPlanOutput)
        raw_response = await structured_llm.ainvoke(messages)
        return cast(StructuredPlanOutput, raw_response).questions

    async def try_cerebras():
        from config.llm_factory import get_cerebras_llm
        cerebras = get_cerebras_llm()
        for attempt in range(3):
            try:
                return await run_planner(cerebras)
            except CerebrasRateLimitError:
                wait = (attempt + 1) * 15
                logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
                await asyncio.sleep(wait)
        raise RuntimeError(ALL_EXHAUSTED_MSG)

    try:
        questions = await run_planner(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Planner Node: primary LLM exhausted. Switching to fallback.")
            from config.llm_factory import get_fallback_llm
            try:
                questions = await run_planner(get_fallback_llm())
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Planner Node: both Groq keys exhausted. Switching to Cerebras.")
                    questions = await try_cerebras()
                else:
                    raise
        else:
            raise

    logger.info(f"Planner successfully constructed blueprint consisting of {len(questions)} items.")

    state_update: dict[str, Any] = {"research_plan": questions}
    if state.get("iteration") is None:
        state_update["iteration"] = 0

    return state_update