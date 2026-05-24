import logging
from typing import Any
from langchain_groq import ChatGroq
from groq import RateLimitError
from config.settings import settings
from graph.research_graph import compile_research_graph
from state.research_state import ResearchStateInput

logger = logging.getLogger("research_agent.agents.research_agent")


def build_llm(api_key: str) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        groq_api_key=api_key
    )


def get_llm_with_fallback() -> ChatGroq:
    """Returns primary LLM. Falls back to secondary key if primary is unavailable."""
    primary_key = settings.GROQ_API_KEY.get_secret_value()
    fallback_key = settings.GROQ_API_KEY_2.get_secret_value() if settings.GROQ_API_KEY_2 else None

    # Quick check — try to list models with primary key to detect if it's rate limited
    try:
        from groq import Groq
        client = Groq(api_key=primary_key)
        client.models.list()
        logger.info("Primary Groq key is active.")
        return build_llm(primary_key)
    except RateLimitError:
        if fallback_key:
            logger.warning("Primary Groq key rate limited. Switching to fallback key.")
            return build_llm(fallback_key)
        raise
    except Exception:
        # Not a rate limit issue — use primary anyway
        return build_llm(primary_key)


class AutonomousResearchAgent:
    """Production interface engineered to execute iterative market intelligence operations."""

    def __init__(self) -> None:
        logger.info("Initializing Autonomous Market Research Agent runtime powered by Groq.")
        self.primary_key = settings.GROQ_API_KEY.get_secret_value()
        self.fallback_key = settings.GROQ_API_KEY_2.get_secret_value() if settings.GROQ_API_KEY_2 else None
        self.llm = build_llm(self.primary_key)
        self.graph = compile_research_graph()

    async def execute_research(self, idea: str, max_iterations: int | None = None) -> dict[str, Any]:
        """Runs the compiled graph to completion. Auto-switches to fallback key on rate limit."""
        validated_input = ResearchStateInput(
            idea=idea,
            max_iterations=max_iterations or settings.DEFAULT_MAX_ITERATIONS
        )
        initial_state = {
            "idea": validated_input.idea,
            "max_iterations": validated_input.max_iterations,
            "research_plan": [],
            "gathered_data": [],
            "insights": [],
            "iteration": 0,
            "reflection_verdict": {},
            "final_report": ""
        }

        async def run_with_llm(llm: ChatGroq) -> dict[str, Any]:
            config = {"configurable": {"llm": llm}}
            return await self.graph.ainvoke(initial_state, config=config)

        try:
            logger.info(f"Triggering research workflow for concept: '{idea[:50]}...'")
            return await run_with_llm(self.llm)

        except RateLimitError as e:
            if "tokens per day" in str(e) and self.fallback_key:
                logger.warning("Primary Groq key daily token limit hit. Switching to fallback key automatically.")
                self.llm = build_llm(self.fallback_key)
                return await run_with_llm(self.llm)
            raise

        except Exception as exc:
            logger.critical(f"Critical execution failure: {str(exc)}", exc_info=True)
            raise exc
