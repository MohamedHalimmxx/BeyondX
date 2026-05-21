import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel

from prompts.research_prompt import REFLECTION_HUMAN_TEMPLATE, REFLECTION_SYSTEM_PROMPT
from state.research_state import ResearchState, ReflectionVerdict

logger = logging.getLogger("research_agent.nodes.reflection_node")


async def reflection_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    """Audits the accumulated insights matrix to determine loop progress status.
    
    Args:
        state: Comprehensive current operational execution scope.
        config: Dependency configuration containing structural runtimes.
        
    Returns:
        A dictionary containing the parsed ReflectionVerdict to handle routing steps.
    """
    logger.info("Executing Reflection Node: Evaluating qualitative research completeness.")

    idea = state.get("idea", "")
    plan = state.get("research_plan", [])
    insights = state.get("insights", [])
    current_iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if not plan or not insights:
        logger.warning("Empty plan or insights detected. Requesting immediate research recovery route.")
        return {
            "reflection_verdict": {
                "is_complete": False,
                "reasoning": "Initial data portfolio states are empty. Forcing loop continuation.",
                "next_question": plan[0] if plan else "Identify market dynamics"
            }
        }

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        error_msg = "Critical dependency missing: 'llm' must be injected into graph configuration context."
        logger.error(error_msg)
        raise KeyError(error_msg)

    # Bind the structured state schema to guarantee deterministic auditing outcomes
    structured_llm = llm.with_structured_output(ReflectionVerdict)

    # Format messaging blocks safely
    messages = [
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": REFLECTION_HUMAN_TEMPLATE.format(
            idea=idea,
            plan="\n".join([f"- {q}" for q in plan]),
            insights="\n".join([f"- {i}" for i in insights]),
            iteration=current_iteration
        )}
    ]

    try:
        logger.debug(f"Dispatching structural auditing payload to LLM context at cycle {current_iteration}.")
        raw_response = await structured_llm.ainvoke(messages)
        verdict = cast(ReflectionVerdict, raw_response)

        logger.info(f"Reflection checkpoint complete. Verdict -> Is Complete: {verdict.is_complete}. "
                    f"Reasoning: {verdict.reasoning}")

        if current_iteration >= max_iterations and not verdict.is_complete:
            logger.warning(f"Iteration limit reached ({current_iteration}/{max_iterations}). "
                           f"Overriding completeness state to break potential infinite loop.")
            return {
                "reflection_verdict": {
                    "is_complete": True,
                    "reasoning": "Iteration cap threshold hit. Advancing automatically to synthesis phase.",
                    "next_question": None
                }
            }

        # Return standard state evaluation package
        return {
            "reflection_verdict": {
                "is_complete": verdict.is_complete,
                "reasoning": verdict.reasoning,
                "next_question": verdict.next_question
            }
        }

    except Exception as exc:
        logger.error(f"Error encountered during node reflection verification cycle: {str(exc)}", exc_info=True)
        return {
            "reflection_verdict": {
                "is_complete": True,
                "reasoning": f"Audit execution failure bypassed safely: {str(exc)}",
                "next_question": None
            }
        }