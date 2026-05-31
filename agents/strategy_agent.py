"""Orchestration client wrapper for running the Strategy Generation pipeline."""

import logging
from typing import Any
from langchain_groq import ChatGroq

from config.settings import settings
from nodes.strategy_node import strategy_node

logger = logging.getLogger("research_agent.agents.strategy_agent")


class StrategyWriterAgent:
    """Provides a structural entry point to build brand playbooks from past data dumps."""

    def __init__(self) -> None:
        logger.info("Initializing stand-alone Strategy Writer execution context.")
        self.llm = ChatGroq(
            model=settings.LLM_MODEL,
            temperature=0.3,  
            groq_api_key=settings.GROQ_API_KEY.get_secret_value()
        )

    async def generate_plan(self, research_state: dict[str, Any]) -> str:
        """Runs the standalone strategy block directly from an input state payload."""
        config = {"configurable": {"llm": self.llm}}
        
        # Execute the isolated node directly
        result_state = await strategy_node(state=research_state, config=config)
        return result_state.get("final_strategic_brief", "")