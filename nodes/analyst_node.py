import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel

from prompts.analyst_prompts import ANALYST_SYSTEM_PROMPT, ANALYST_HUMAN_TEMPLATE
from state.analyst_state import BrandAnalystOutput

logger = logging.getLogger("research_agent.nodes.analyst_node")


async def analyst_node(
    idea: str,
    research_report: str,
    insights: list[str],
    llm: BaseChatModel
) -> BrandAnalystOutput:
    """
    Analyzes market research output and produces a structured brand positioning analysis.

    Args:
        idea: The original business idea.
        research_report: The final markdown report from the research agent.
        insights: Raw insight list accumulated during research.
        llm: The injected language model instance.

    Returns:
        BrandAnalystOutput with competitor map, white space, pain points, and positioning.
    """
    logger.info("Executing Analyst Node: Running brand positioning analysis.")

    formatted_insights = "\n".join([f"- {i}" for i in insights])

    messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {"role": "user", "content": ANALYST_HUMAN_TEMPLATE.format(
            idea=idea,
            research_report=research_report,
            insights=formatted_insights
        )}
    ]

    structured_llm = llm.with_structured_output(BrandAnalystOutput)

    try:
        result = cast(BrandAnalystOutput, await structured_llm.ainvoke(messages))
        logger.info(
            f"Analyst Node complete. "
            f"{len(result.competitors)} competitors mapped, "
            f"{len(result.pain_points)} pain points identified."
        )
        return result

    except Exception as exc:
        logger.error(f"Analyst node failed: {str(exc)}", exc_info=True)
        raise exc
