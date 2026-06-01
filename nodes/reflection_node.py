import logging
from typing import Any
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio

from config.llm_factory import get_fallback_llm
from prompts.research_prompt import REFLECTION_SYSTEM_PROMPT, REFLECTION_HUMAN_TEMPLATE
from state.research_state import ResearchState, ReflectionVerdict

logger = logging.getLogger("research_agent.nodes.reflection_node")

ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers are currently rate-limited or overloaded.\n"
    "   (Groq key 1, Groq key 2, Cerebras)\n"
    "   Please wait a few minutes and run again.\n"
)


async def reflection_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("Executing Reflection Node: Evaluating qualitative research completeness.")

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)
    research_plan = state.get("research_plan", [])
    insights = state.get("insights", [])

    if not insights and not research_plan:
        logger.warning("Empty plan or insights detected. Forcing loop continuation.")
        return {"is_complete": False, "reflection_reasoning": "No data yet."}

    if iteration >= max_iterations:
        logger.warning(f"Iteration limit reached ({iteration}/{max_iterations}). Forcing completion.")
        return {"is_complete": True, "reflection_reasoning": "Iteration cap hit."}

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        raise KeyError("Critical dependency missing: 'llm' not found in runtime config.")

    messages = [
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": REFLECTION_HUMAN_TEMPLATE.format(
            idea=state.get("idea", ""),
            plan="\n".join(f"- {q}" for q in research_plan),
            insights="\n".join(f"- {i}" for i in insights),
            iteration=iteration
        )}
    ]

    async def invoke(active_llm):
        structured = active_llm.with_structured_output(ReflectionVerdict)
        return await structured.ainvoke(messages)

    async def try_cerebras():
        from config.llm_factory import get_cerebras_llm
        cerebras = get_cerebras_llm()
        for attempt in range(3):
            try:
                return await invoke(cerebras)
            except CerebrasRateLimitError:
                wait = (attempt + 1) * 15
                logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
                await asyncio.sleep(wait)
        raise RuntimeError(ALL_EXHAUSTED_MSG)

    try:
        verdict = await invoke(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Reflection Node: primary LLM rate limited. Switching to fallback.")
            try:
                verdict = await invoke(get_fallback_llm())
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Reflection Node: both Groq keys exhausted. Switching to Cerebras.")
                    verdict = await try_cerebras()
                else:
                    raise
        else:
            raise

    logger.info(f"Reflection complete. Is Complete: {verdict.is_complete}. Reasoning: {verdict.reasoning}")
    return {
        "is_complete": verdict.is_complete,
        "reflection_reasoning": verdict.reasoning
    }