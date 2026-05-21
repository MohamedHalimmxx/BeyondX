import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from prompts.research_prompt import (
    RESEARCH_EXTRACTOR_HUMAN_TEMPLATE,
    RESEARCH_EXTRACTOR_SYSTEM_PROMPT,
)
from state.research_state import ResearchState
from tools.search_tool import MarketSearchTool

logger = logging.getLogger("research_agent.nodes.research_node")


class DistilledInsightsOutput(BaseModel):
    """Pydantic model forcing structured high-signal insight list extraction."""
    
    findings: list[str] = Field(
        ..., 
        description="High-signal metrics, concrete competitive variables, or trend factors extracted from text."
    )


async def research_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    """Iteratively resolves open plan questions by hunting data through external wrappers.
    
    Args:
        state: Comprehensive current operational execution scope.
        config: Dependency configuration containing structural runtimes.
    """
    logger.info("Executing Research Node: Commencing data collection cycle.")
    
    plan = state.get("research_plan", [])
    current_idx = state.get("iteration", 0)
    idea = state.get("idea", "")

    if not plan:
        logger.warning("Research Node received an uninitialized plan matrix. Halting discovery early.")
        return {}

    target_question_idx = current_idx % len(plan)
    target_question = plan[target_question_idx]
    
    logger.info(f"Targeting question index [{target_question_idx}/{len(plan)}]: '{target_question}'")

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        error_msg = "Critical core dependency missing: 'llm' must be injected into graph configuration."
        logger.error(error_msg)
        raise KeyError(error_msg)

    search_tool = MarketSearchTool()
    structured_llm = llm.with_structured_output(DistilledInsightsOutput)

    raw_search_dump = await search_tool.run_async(query=f"{idea} {target_question}")

    messages = [
        {"role": "system", "content": RESEARCH_EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": RESEARCH_EXTRACTOR_HUMAN_TEMPLATE.format(
            idea=idea,
            question=target_question,
            raw_data=raw_search_dump
        )}
    ]

    try:
        logger.debug("Dispatching raw data chunk to analytical LLM context for insight filtering.")
        raw_response = await structured_llm.ainvoke(messages)
        distilled_data = cast(DistilledInsightsOutput, raw_response)
        
        new_findings = distilled_data.findings
        logger.info(f"Extracted {len(new_findings)} primary high-signal entries during loop turn.")

        
        return {
            "gathered_data": [f"Question addressed: {target_question}\n{raw_search_dump}"],
            "insights": new_findings,
            "iteration": current_idx + 1  
        }

    except Exception as exc:
        logger.error(f"Data mapping execution breakdown in research node sequence: {str(exc)}", exc_info=True)
        return {
            "gathered_data": [f"Question addressed: {target_question}\n{raw_search_dump}"],
            "iteration": current_idx + 1
        }