"""Shared LLM invocation utility — single fallback chain for all nodes."""

import asyncio
import logging
from typing import TypeVar, Callable, Awaitable
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError

from config.llm_factory import get_fallback_llm

logger = logging.getLogger("research_agent.utils.llm_utils")

T = TypeVar("T")

ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers exhausted (Groq key 1, Groq key 2, Cerebras).\n"
    "   Please wait a few minutes and run again.\n"
)

_RATE_LIMIT_SIGNALS = ("tokens per day", "rate_limit_exceeded", "429")


def _is_rate_limit(exc: Exception) -> bool:
    return any(s in str(exc) for s in _RATE_LIMIT_SIGNALS)


async def invoke_with_fallback(
    fn: Callable[..., Awaitable[T]],
    llm: BaseChatModel,
    *args,
    cerebras_temperature: float = 0.2,
    **kwargs,
) -> T:
    """
    Call fn(llm, *args, **kwargs) with automatic fallback chain:
    Groq key 1 → Groq key 2 → Cerebras (3 attempts with backoff).

    fn must accept `llm` as its first positional argument.
    """
    # Groq key 1
    try:
        return await fn(llm, *args, **kwargs)
    except Exception as e:
        if not _is_rate_limit(e):
            raise
        logger.warning(f"Primary LLM rate limited ({fn.__name__}). Switching to fallback.")

    # Groq key 2
    try:
        return await fn(get_fallback_llm(), *args, **kwargs)
    except Exception as e2:
        if not _is_rate_limit(e2):
            raise
        logger.warning(f"Fallback LLM rate limited ({fn.__name__}). Switching to Cerebras.")

    # Cerebras
    from config.llm_factory import get_cerebras_llm
    cerebras = get_cerebras_llm(temperature=cerebras_temperature)
    for attempt in range(3):
        try:
            return await fn(cerebras, *args, **kwargs)
        except CerebrasRateLimitError:
            wait = (attempt + 1) * 15
            logger.warning(
                f"Cerebras queue full ({fn.__name__}). "
                f"Retrying in {wait}s (attempt {attempt+1}/3)."
            )
            await asyncio.sleep(wait)
        except Exception as err:
            if attempt == 2:
                raise
            logger.warning(f"Cerebras error ({fn.__name__}): {err}. Retrying.")
            await asyncio.sleep(10)

    raise RuntimeError(ALL_EXHAUSTED_MSG)