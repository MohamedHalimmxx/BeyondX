import logging
from typing import Any
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio

from config.llm_factory import get_fallback_llm
from prompts.research_prompt import REPORT_SYNTHESIS_SYSTEM_PROMPT, REPORT_SYNTHESIS_HUMAN_TEMPLATE
from state.research_state import ResearchState

logger = logging.getLogger("research_agent.nodes.report_node")

ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers are currently rate-limited or overloaded.\n"
    "   (Groq key 1, Groq key 2, Cerebras)\n"
    "   Please wait a few minutes and run again.\n"
)


async def report_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("Executing Report Node: Initiating final intelligence synthesis.")

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        raise KeyError("Critical dependency missing: 'llm' not found in runtime config.")

    idea = state.get("idea", "")
    insights = state.get("insights", [])
    gathered_data = state.get("gathered_data", [])

    messages = [
        {"role": "system", "content": REPORT_SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": REPORT_SYNTHESIS_HUMAN_TEMPLATE.format(
            idea=idea,
            insights="\n".join(f"- {i}" for i in insights),
            raw_data="\n\n".join(gathered_data)
        )}
    ]

    async def invoke(active_llm):
        response = await active_llm.ainvoke(messages)
        return response.content

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
        report_content = await invoke(llm)
        logger.info(f"Report Node compiled final document. Length: {len(report_content)} characters.")
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Report Node: primary LLM rate limited. Switching to fallback.")
            try:
                report_content = await invoke(get_fallback_llm())
                logger.info(f"Report Node compiled via fallback. Length: {len(report_content)} characters.")
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Report Node: both Groq keys exhausted. Switching to Cerebras.")
                    report_content = await try_cerebras()
                    logger.info(f"Report Node compiled via Cerebras. Length: {len(report_content)} characters.")
                else:
                    raise
        else:
            raise

    return {"report": report_content}