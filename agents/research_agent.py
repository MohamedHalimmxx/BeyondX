import logging
from typing import Any
from langchain_groq import ChatGroq
from groq import RateLimitError
from config.settings import settings
from config.llm_factory import get_research_primary_llm, get_research_fallback_llm
from graph.research_graph import compile_research_graph
from state.research_state import ResearchStateInput

logger = logging.getLogger("research_agent.agents.research_agent")


def build_llm(api_key: str) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        groq_api_key=api_key,
    )


class AutonomousResearchAgent:
    """Production interface engineered to execute iterative market intelligence operations."""

    def __init__(self) -> None:
        logger.info("Initializing Autonomous Market Research Agent runtime powered by Groq.")
        self.llm = get_research_primary_llm()
        self.graph = compile_research_graph()

    async def execute_research(self, idea: str, max_iterations: int | None = None) -> dict[str, Any]:
        validated_input = ResearchStateInput(
            idea=idea,
            max_iterations=max_iterations or settings.DEFAULT_MAX_ITERATIONS,
        )
        initial_state = {
            "idea": validated_input.idea,
            "max_iterations": validated_input.max_iterations,
        }
        logger.info(f"Triggering research workflow for concept: '{idea[:50]}...'")
        config = {"configurable": {"llm": self.llm}}
        try:
            result = await self.graph.ainvoke(initial_state, config=config)
            return result
        except RateLimitError:
            logger.warning("Research agent: primary key rate limited. Switching to fallback.")
            fallback_llm = get_research_fallback_llm()
            config = {"configurable": {"llm": fallback_llm}}
            return await self.graph.ainvoke(initial_state, config=config)