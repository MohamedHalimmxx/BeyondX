import logging
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError
import asyncio
from config.llm_factory import get_naming_llm, get_fallback_llm
from nodes.naming_node import naming_node

logger = logging.getLogger("research_agent.agents.naming_agent")
ALL_EXHAUSTED_MSG = "\n\n⚠️  All LLM providers exhausted.\n   Please wait a few minutes and run again.\n"

class BrandNamingAgent:
    def __init__(self):
        logger.info("Initializing Brand Naming Agent.")
        self.llm = get_naming_llm(temperature=0.7)

    async def generate_names(self, idea, positioning_statement, analysis, brand_brief):
        async def run(llm):
            return await naming_node(idea=idea, positioning_statement=positioning_statement, analysis=analysis, brand_brief=brand_brief, llm=llm)
        try:
            return await run(self.llm)
        except RateLimitError as e:
            if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
                logger.warning("Naming Agent: rate limited. Switching to fallback.")
                try:
                    return await run(get_fallback_llm(temperature=0.7))
                except RateLimitError as e2:
                    if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                        logger.warning("Both Groq keys exhausted. Switching to Cerebras.")
                        from config.llm_factory import get_cerebras_llm
                        cerebras = get_cerebras_llm(temperature=0.7)
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
            logger.error(f"Naming Agent failed: {str(exc)}", exc_info=True)
            raise