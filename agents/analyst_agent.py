import logging
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio
from config.llm_factory import get_analyst_llm, get_fallback_llm
from nodes.analyst_node import analyst_node

logger = logging.getLogger("research_agent.agents.analyst_agent")
ALL_EXHAUSTED_MSG = "\n\n⚠️  All LLM providers exhausted.\n   Please wait a few minutes and run again.\n"

class BrandAnalystAgent:
    def __init__(self):
        logger.info("Initializing Brand Analyst Agent.")
        self.llm = get_analyst_llm(temperature=0.2)

    async def execute_analysis(self, idea, research_report, insights):
        async def run(llm):
            return await analyst_node(idea=idea, research_report=research_report, insights=insights, llm=llm)
        logger.info(f"Starting brand analysis for: '{idea[:50]}...'")
        try:
            return await run(self.llm)
        except RateLimitError as e:
            if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
                logger.warning("Primary LLM rate limited. Switching to fallback.")
                try:
                    return await run(get_fallback_llm(temperature=0.2))
                except RateLimitError as e2:
                    if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                        logger.warning("Both Groq keys exhausted. Switching to Cerebras.")
                        from config.llm_factory import get_cerebras_llm
                        cerebras = get_cerebras_llm(temperature=0.2)
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
            logger.error(f"Brand analyst failed: {str(exc)}", exc_info=True)
            raise