import logging
from typing import Any
from langchain_groq import ChatGroq 
from config.settings import settings
from graph.research_graph import compile_research_graph
from state.research_state import ResearchStateInput

logger = logging.getLogger("research_agent.agents.research_agent")


class AutonomousResearchAgent:
    """Production interface engineered to execute iterative market intelligence operations."""

    def __init__(self) -> None:
        """Initializes the execution engine dependencies and compiles the runtime graph."""
        logger.info("Initializing Autonomous Market Research Agent runtime powered by Groq.")
        
        # Instantiate the Groq inference engine client dependency
        self.llm = ChatGroq(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            groq_api_key=settings.GROQ_API_KEY.get_secret_value()
        )
        
        # Compile the underlying state graph structure
        self.graph = compile_research_graph()

    async def execute_research(self, idea: str, max_iterations: int | None = None) -> dict[str, Any]:
        """Runs the compiled graph synchronously to completion and yields the final payload state."""
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

        config = {
            "configurable": {
                "llm": self.llm  
            }
        }

        try:
            logger.info(f"Triggering research workflow process execution for concept: '{idea[:50]}...'")
            final_output = await self.graph.ainvoke(initial_state, config=config)
            return final_output
            
        except Exception as exc:
            logger.critical(f"Critical execution failure during agent runtime execution sequence: {str(exc)}", exc_info=True)
            raise exc