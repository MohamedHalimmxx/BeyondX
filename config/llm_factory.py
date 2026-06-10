import logging
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings

logger = logging.getLogger("research_agent.config.llm_factory")


# ── Core builders ─────────────────────────────────────────────────────────

def build_groq(api_key: str, temperature: float | None = None) -> ChatGroq:
    return ChatGroq(
        model=settings.LLM_MODEL,
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        groq_api_key=api_key,
    )


def build_cerebras(temperature: float | None = None):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="gpt-oss-120b",
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        api_key=settings.CEREBRAS_API_KEY.get_secret_value(),
        base_url="https://api.cerebras.ai/v1",
    )


def build_gemini(temperature: float | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        google_api_key=settings.GEMINI_API_KEY.get_secret_value(),
    )


def _resolve(key_attr: str, temperature: float | None = None) -> ChatGroq:
    """
    Resolve a named key from settings, falling back to Cerebras if missing.
    key_attr: attribute name on settings e.g. 'GROQ_PLANNER_KEY'
    """
    key_obj = getattr(settings, key_attr, None)
    if key_obj:
        return build_groq(api_key=key_obj.get_secret_value(), temperature=temperature)
    logger.warning(f"{key_attr} not set — falling back to Cerebras.")
    if settings.CEREBRAS_API_KEY:
        return build_cerebras(temperature=temperature)
    raise RuntimeError(f"{key_attr} not set and no Cerebras fallback available.")


# ── Legacy getters (kept for backward compat) ─────────────────────────────

def get_primary_llm(temperature: float | None = None) -> ChatGroq:
    return build_groq(
        api_key=settings.GROQ_API_KEY.get_secret_value(),
        temperature=temperature,
    )


def get_fast_llm() -> ChatGroq:
    return build_groq(api_key=settings.GROQ_API_KEY.get_secret_value(), temperature=0.0)


def get_fallback_llm(temperature: float | None = None):
    if settings.GROQ_API_KEY_2:
        logger.warning("Switching to Groq fallback key.")
        return build_groq(api_key=settings.GROQ_API_KEY_2.get_secret_value(), temperature=temperature)
    if getattr(settings, "GROQ_API_KEY_3", None):
        logger.warning("Switching to Groq key 3.")
        return build_groq(api_key=settings.GROQ_API_KEY_3.get_secret_value(), temperature=temperature)
    if settings.CEREBRAS_API_KEY:
        logger.warning("Switching to Cerebras fallback.")
        return build_cerebras(temperature=temperature)
    if settings.GEMINI_API_KEY:
        logger.warning("Switching to Gemini Flash fallback.")
        return build_gemini(temperature=temperature)
    raise RuntimeError("All LLM keys exhausted.")


def get_cerebras_llm(temperature: float | None = None):
    if settings.CEREBRAS_API_KEY:
        logger.warning("Switching to Cerebras fallback.")
        return build_cerebras(temperature=temperature)
    if settings.GEMINI_API_KEY:
        logger.warning("Switching to Gemini Flash fallback.")
        return build_gemini(temperature=temperature)
    raise RuntimeError("No fallback keys available.")


# ── Dedicated getters — one per BrandGenius node ─────────────────────────

def get_research_primary_llm(temperature: float | None = None) -> ChatGroq:
    """research_agent.py — primary key"""
    return _resolve("GROQ_RESEARCH_PRIMARY_KEY", temperature)


def get_research_fallback_llm(temperature: float | None = None) -> ChatGroq:
    """research_agent.py — fallback key"""
    return _resolve("GROQ_RESEARCH_FALLBACK_KEY", temperature)


def get_research_node_llm(temperature: float | None = None) -> ChatGroq:
    """research_node.py"""
    return _resolve("GROQ_RESEARCH_NODE_KEY", temperature)


def get_planner_llm(temperature: float | None = None) -> ChatGroq:
    """planner_node.py"""
    return _resolve("GROQ_PLANNER_KEY", temperature)


def get_reflection_llm(temperature: float | None = None) -> ChatGroq:
    """reflection_node.py"""
    return _resolve("GROQ_REFLECTION_KEY", temperature)


def get_report_llm(temperature: float | None = None) -> ChatGroq:
    """report_node.py"""
    return _resolve("GROQ_REPORT_KEY", temperature)


def get_analyst_llm(temperature: float | None = None) -> ChatGroq:
    """analyst_agent.py"""
    return _resolve("GROQ_ANALYST_KEY", temperature)


def get_strategy_llm(temperature: float | None = None) -> ChatGroq:
    """strategy_agent.py"""
    return _resolve("GROQ_STRATEGY_KEY", temperature)


def get_naming_llm(temperature: float | None = None) -> ChatGroq:
    """naming_agent.py"""
    return _resolve("GROQ_NAMING_KEY", temperature)


def get_brand_identity_llm(temperature: float | None = None) -> ChatGroq:
    """brand_identity_agent.py"""
    return _resolve("GROQ_BRAND_IDENTITY_KEY", temperature)