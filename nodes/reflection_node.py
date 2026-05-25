import logging
from typing import Any, cast
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError

from prompts.research_prompt import REFLECTION_HUMAN_TEMPLATE, REFLECTION_SYSTEM_PROMPT
from state.research_state import ResearchState, ReflectionVerdict
from config.llm_factory import get_fallback_llm

logger = logging.getLogger("research_agent.nodes.reflection_node")


async def reflection_node(state: ResearchState, config: dict[str, Any]) -> dict[str, Any]:
    """Audits accumulated insights to determine if research loop should continue."""
    logger.info("Executing Reflection Node: Evaluating qualitative research completeness.")

    idea = state.get("idea", "")
    plan = state.get("research_plan", [])
    insights = state.get("insights", [])
    current_iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if not plan or not insights:
        logger.warning("Empty plan or insights detected. Forcing loop continuation.")
        return {
            "reflection_verdict": {
                "is_complete": False,
                "reasoning": "Initial data portfolio is empty. Forcing loop continuation.",
                "next_question": plan[0] if plan else "Identify market dynamics"
            }
        }

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if not llm:
        raise KeyError("Critical dependency missing: 'llm' must be injected into graph configuration context.")

    messages = [
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": REFLECTION_HUMAN_TEMPLATE.format(
            idea=idea,
            plan="\n".join([f"- {q}" for q in plan]),
            insights="\n".join([f"- {i}" for i in insights]),
            iteration=current_iteration
        )}
    ]

    async def invoke(active_llm) -> ReflectionVerdict:
        structured = active_llm.with_structured_output(ReflectionVerdict)
        return cast(ReflectionVerdict, await structured.ainvoke(messages))

    try:
        verdict = await invoke(llm)

    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Reflection Node: primary LLM rate limited. Switching to fallback.")
            try:
                fallback = get_fallback_llm()
                verdict = await invoke(fallback)
            except Exception:
                logger.warning("Fallback also failed in reflection. Forcing completion to avoid crash.")
                return {
                    "reflection_verdict": {
                        "is_complete": True,
                        "reasoning": "All LLMs exhausted during reflection. Advancing to synthesis.",
                        "next_question": None
                    }
                }
        else:
            raise

    except Exception as exc:
        logger.error(f"Reflection Node error: {str(exc)}", exc_info=True)
        return {
            "reflection_verdict": {
                "is_complete": True,
                "reasoning": f"Reflection bypassed safely: {str(exc)}",
                "next_question": None
            }
        }

    logger.info(f"Reflection complete. Is Complete: {verdict.is_complete}. Reasoning: {verdict.reasoning}")

    if current_iteration >= max_iterations and not verdict.is_complete:
        logger.warning(f"Iteration limit reached ({current_iteration}/{max_iterations}). Forcing completion.")
        return {
            "reflection_verdict": {
                "is_complete": True,
                "reasoning": "Iteration cap hit. Advancing to synthesis phase.",
                "next_question": None
            }
        }

    return {
        "reflection_verdict": {
            "is_complete": verdict.is_complete,
            "reasoning": verdict.reasoning,
            "next_question": verdict.next_question
        }
    }
