import logging
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from groq import RateLimitError
from config.settings import settings

logger = logging.getLogger("research_agent.config.llm_factory")


def build_groq(api_key: str, temperature: float | None = None) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=temperature or settings.LLM_TEMPERATURE,
        groq_api_key=api_key
    )


def build_gemini(temperature: float | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        temperature=temperature or settings.LLM_TEMPERATURE,
        google_api_key=settings.GEMINI_API_KEY.get_secret_value()
    )


def get_primary_llm(temperature: float | None = None):
    """Returns the primary Groq LLM."""
    return build_groq(
        api_key=settings.GROQ_API_KEY.get_secret_value(),
        temperature=temperature
    )


def get_fallback_llm(temperature: float | None = None):
    """
    Returns the best available fallback LLM.
    Order: Groq key 2 → Gemini Flash
    """
    if settings.GROQ_API_KEY_2:
        logger.warning("Switching to Groq fallback key.")
        return build_groq(
            api_key=settings.GROQ_API_KEY_2.get_secret_value(),
            temperature=temperature
        )
    if settings.GEMINI_API_KEY:
        logger.warning("Switching to Gemini Flash fallback.")
        return build_gemini(temperature=temperature)
    raise RuntimeError("All LLM keys exhausted. Add GROQ_API_KEY_2 or GEMINI_API_KEY to .env")


async def run_with_fallback(llm_call, temperature: float | None = None):
    """
    Executes an async LLM call with automatic fallback on rate limit.
    
    Usage:
        result = await run_with_fallback(lambda llm: llm.ainvoke(messages))
    """
    try:
        llm = get_primary_llm(temperature)
        return await llm_call(llm)
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning(f"Primary LLM rate limited: {str(e)[:80]}")
            llm = get_fallback_llm(temperature)
            return await llm_call(llm)
        raise
