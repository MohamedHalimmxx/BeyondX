import logging
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings

logger = logging.getLogger("research_agent.config.llm_factory")


def build_groq(api_key: str, temperature: float | None = None) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        groq_api_key=api_key
    )


def build_cerebras(temperature: float | None = None):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="gpt-oss-120b",
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        api_key=settings.CEREBRAS_API_KEY.get_secret_value(),
        base_url="https://api.cerebras.ai/v1"
    )


def build_gemini(temperature: float | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        google_api_key=settings.GEMINI_API_KEY.get_secret_value()
    )


def get_primary_llm(temperature: float | None = None) -> ChatGroq:
    return build_groq(
        api_key=settings.GROQ_API_KEY.get_secret_value(),
        temperature=temperature
    )


def get_fast_llm() -> ChatGroq:
    return build_groq(
        api_key=settings.GROQ_API_KEY.get_secret_value(),
        temperature=0.0
    )


def get_fallback_llm(temperature: float | None = None):
    """
    Fallback chain: Groq key 2 → Groq key 3 → Cerebras → Gemini
    """
    if settings.GROQ_API_KEY_2:
        logger.warning("Switching to Groq fallback key.")
        return build_groq(
            api_key=settings.GROQ_API_KEY_2.get_secret_value(),
            temperature=temperature
        )
    if getattr(settings, "GROQ_API_KEY_3", None):
        logger.warning("Switching to Groq key 3.")
        return build_groq(
            api_key=settings.GROQ_API_KEY_3.get_secret_value(),
            temperature=temperature
        )
    if settings.CEREBRAS_API_KEY:
        logger.warning("Switching to Cerebras fallback.")
        return build_cerebras(temperature=temperature)
    if settings.GEMINI_API_KEY:
        logger.warning("Switching to Gemini Flash fallback.")
        return build_gemini(temperature=temperature)
    raise RuntimeError("All LLM keys exhausted.")


def get_cerebras_llm(temperature: float | None = None):
    """Direct Cerebras access — bypasses Groq keys entirely."""
    if settings.CEREBRAS_API_KEY:
        logger.warning("Switching to Cerebras fallback.")
        return build_cerebras(temperature=temperature)
    if settings.GEMINI_API_KEY:
        logger.warning("Switching to Gemini Flash fallback.")
        return build_gemini(temperature=temperature)
    raise RuntimeError("No fallback keys available.")