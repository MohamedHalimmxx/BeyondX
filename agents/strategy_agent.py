import logging
from typing import Any, Tuple
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio
from config.llm_factory import get_strategy_llm, get_fallback_llm
from nodes.strategy_node import strategy_node

logger = logging.getLogger("research_agent.agents.strategy_agent")
ALL_EXHAUSTED_MSG = "\n\n⚠️  All LLM providers exhausted.\n   Please wait a few minutes and run again.\n"

class StrategyWriterAgent:
    def __init__(self):
        logger.info("Initializing stand-alone Strategy Writer execution context.")
        self.llm = get_strategy_llm(temperature=0.3)

    async def generate_plan(self, research_state: dict[str, Any]) -> Tuple[str, Any]:
        async def run(llm):
            config = {"configurable": {"llm": llm}}
            result_state = await strategy_node(state=research_state, config=config)
            return (
                result_state.get("final_strategic_brief", ""),
                result_state.get("validated_plan", None),
            )
        try:
            return await run(self.llm)
        except RateLimitError as e:
            if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
                logger.warning("Strategy Writer: rate limited. Switching to fallback.")
                try:
                    return await run(get_fallback_llm(temperature=0.3))
                except RateLimitError as e2:
                    if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                        logger.warning("Both Groq keys exhausted. Switching to Cerebras.")
                        from config.llm_factory import get_cerebras_llm
                        cerebras = get_cerebras_llm(temperature=0.3)
                        for attempt in range(3):
                            try:
                                return await run(cerebras)
                            except CerebrasRateLimitError:
                                wait = (attempt + 1) * 15
                                logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
                                await asyncio.sleep(wait)
                        raise RuntimeError(ALL_EXHAUSTED_MSG)
                    raise
            raise
        except Exception as exc:
            logger.error(f"Strategy Writer failed: {str(exc)}", exc_info=True)
            raise