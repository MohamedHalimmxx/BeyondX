import logging
from langchain_groq import ChatGroq
from groq import RateLimitError
from config.settings import settings
from nodes.analyst_node import analyst_node
from state.analyst_state import BrandAnalystOutput

logger = logging.getLogger("research_agent.agents.analyst_agent")


def build_llm(api_key: str) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=0.2,
        groq_api_key=api_key
    )


class BrandAnalystAgent:
    """
    Consumes market research output and produces structured brand positioning analysis.
    Runs after the research agent completes.
    """

    def __init__(self) -> None:
        logger.info("Initializing Brand Analyst Agent.")
        self.primary_key = settings.GROQ_API_KEY.get_secret_value()
        self.fallback_key = (
            settings.GROQ_API_KEY_2.get_secret_value()
            if settings.GROQ_API_KEY_2 else None
        )
        self.llm = build_llm(self.primary_key)

    async def execute_analysis(
        self,
        idea: str,
        research_report: str,
        insights: list[str]
    ) -> BrandAnalystOutput:
        """
        Runs brand positioning analysis on research output.
        Auto-switches to fallback key on rate limit.
        """
        try:
            logger.info(f"Triggering brand analysis for: '{idea[:50]}...'")
            return await analyst_node(
                idea=idea,
                research_report=research_report,
                insights=insights,
                llm=self.llm
            )

        except RateLimitError as e:
            if "tokens per day" in str(e) and self.fallback_key:
                logger.warning("Primary key rate limited. Switching to fallback.")
                self.llm = build_llm(self.fallback_key)
                return await analyst_node(
                    idea=idea,
                    research_report=research_report,
                    insights=insights,
                    llm=self.llm
                )
            raise

        except Exception as exc:
            logger.error(f"Brand analyst execution failed: {str(exc)}", exc_info=True)
            raise exc
