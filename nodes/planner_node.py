import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from config.settings import settings
from prompts.research_prompt import PLANNER_HUMAN_TEMPLATE, PLANNER_SYSTEM_PROMPT
from state.research_state import ResearchState

logger = logging.getLogger("research_agent.nodes.planner_node")

class StructuredPlanOutput(BaseModel):
    """Pydantic schema to enforce structured questions array from the ChatModel."""
    
    questions: list[str] = Field(
        ...,
        description="A list of explicit, targeted research questions across market, competitor, audience, pricing, and trend vectors."
    )


async def planner_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    """Analyzes a business idea and generates a comprehensive research blueprint.
    
    Args:
        state: The current operational state containing the user business idea.
        config: Configuration dictionary housing the runnable dependencies (e.g., LLM instance).
        
    Returns:
        A state delta containing the populated research plan list.
        
    Raises:
        KeyError: If the required language model dependency is missing from the configuration context.
    """
    logger.info("Executing Planner Node: Processing business velocity alignment.")
    
    idea = state.get("idea", "").strip()
    if not idea:
        logger.warning("Planner Node received an empty business idea string.")
        return {"research_plan": []}

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        error_msg = "Critical dependency missing: 'llm' must be injected via runtime configuration."
        logger.error(error_msg)
        raise KeyError(error_msg)

    # Bind the structured schema variant to ensure deterministic outputs
    structured_llm = llm.with_structured_output(StructuredPlanOutput)

    # Format messaging arrays for execution context
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": PLANNER_HUMAN_TEMPLATE.format(idea=idea)}
    ]

    try:
        logger.debug(f"Dispatching compilation payload to LLM provider for idea: {idea[:60]}...")
        raw_response = await structured_llm.ainvoke(messages)
        plan_output = cast(StructuredPlanOutput, raw_response)
        
        generated_questions = plan_output.questions
        logger.info(f"Planner successfully constructed blueprint consisting of {len(generated_questions)} items.")
        
        # Build state modification payload
        state_update: dict[str, Any] = {
            "research_plan": generated_questions
        }
        
        if state.get("iteration") is None:
            state_update["iteration"] = 0
            logger.debug("Initialized execution loop index trace field to zero.")

        return state_update

    except Exception as exc:
        logger.critical(f"System generation breakdown inside planner node execution sequence: {str(exc)}", exc_info=True)
        raise exc