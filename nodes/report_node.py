import logging
from typing import Any
from langchain_core.language_models.chat_models import BaseChatModel

from prompts.research_prompt import REPORT_SYNTHESIS_HUMAN_TEMPLATE, REPORT_SYNTHESIS_SYSTEM_PROMPT
from state.research_state import ResearchState

logger = logging.getLogger("research_agent.nodes.report_node")


async def report_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    """Synthesizes total research data history into a professional markdown report.
    
    Args:
        state: Comprehensive current operational execution scope.
        config: Dependency configuration containing structural runtimes.
        
    Returns:
        A state delta containing the generated final_report markdown string.
    """
    logger.info("Executing Report Node: Initiating final intelligence synthesis.")

    idea = state.get("idea", "")
    insights = state.get("insights", [])
    gathered_data = state.get("gathered_data", [])

    if not insights and not gathered_data:
        logger.warning("Report Node executed with zero accumulated data indicators. Generating empty template.")
        return {
            "final_report": "# Market Research Report\n\nNo empirical research insights were collected during execution."
        }

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        error_msg = "Critical dependency missing: 'llm' must be injected into graph configuration context."
        logger.error(error_msg)
        raise KeyError(error_msg)

    formatted_insights = "\n".join([f"- {insight}" for insight in insights])
    
    raw_data_summary = "\n\n".join(gathered_data)[:15000]

    messages = [
        {"role": "system", "content": REPORT_SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": REPORT_SYNTHESIS_HUMAN_TEMPLATE.format(
            idea=idea,
            insights=formatted_insights,
            raw_data=raw_data_summary
        )}
    ]

    try:
        logger.debug("Dispatching aggregate research ledger to LLM for final report compilation.")
        
        response = await llm.ainvoke(messages)
        report_content = str(response.content).strip()
        
        logger.info(f"Report Node successfully compiled final document. Total length: {len(report_content)} characters.")
        
        return {
            "final_report": report_content
        }

    except Exception as exc:
        logger.critical(f"System failure during report synthesis phase: {str(exc)}", exc_info=True)
        raise exc