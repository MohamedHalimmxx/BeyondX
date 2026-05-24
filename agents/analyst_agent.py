import logging
from groq import RateLimitError
from config.settings import settings
from config.llm_factory import build_groq, get_fallback_llm
from nodes.analyst_node import analyst_node
from state.analyst_state import BrandAnalystOutput

logger = logging.getLogger("research_agent.agents.analyst_agent")


class BrandAnalystAgent:
    """
    Consumes market research output and produces structured brand positioning analysis.
    Runs after the research agent completes.
    """

    def __init__(self) -> None:
        logger.info("Initializing Brand Analyst Agent.")
        self.llm = build_groq(
            api_key=settings.GROQ_API_KEY.get_secret_value(),
            temperature=0.2
        )

    async def execute_analysis(
        self,
        idea: str,
        research_report: str,
        insights: list[str]
    ) -> BrandAnalystOutput:
        """Runs brand positioning analysis. Auto-switches LLM on rate limit."""

        async def run(llm):
            return await analyst_node(
                idea=idea,
                research_report=research_report,
                insights=insights,
                llm=llm
            )

        try:
            logger.info(f"Starting brand analysis for: '{idea[:50]}...'")
            return await run(self.llm)

        except RateLimitError as e:
            if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
                logger.warning("Primary LLM rate limited. Switching to fallback.")
                self.llm = get_fallback_llm(temperature=0.2)
                return await run(self.llm)
            raise

        except Exception as exc:
            logger.error(f"Brand analyst failed: {str(exc)}", exc_info=True)
            raise exc
