"""Brand Book Agent — Stage 7

Primary: Groq (llama-3.3-70b-versatile) using dedicated brand book keys.
Fallback: Gemini Pro → Flash on GEMINI_BRAND_BOOK_KEY_1/2/3/4 (if Groq fails).
"""

import logging
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings

logger = logging.getLogger("research_agent.agents.brand_book_agent")


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).upper()
    return any(q in msg for q in ("RESOURCE_EXHAUSTED", "429", "QUOTA", "RATE_LIMIT"))


def _get_groq_keys() -> list[tuple[str, str]]:
    """Groq keys for brand book generation — dedicated key first, then shared pool fallback."""
    key_map = [
        (getattr(settings, "GROQ_BRAND_BOOK_KEY", None), "groq_brand_book"),
        (getattr(settings, "GROQ_BRAND_IDENTITY_KEY", None), "groq_brand_identity"),
        (getattr(settings, "GROQ_STRATEGY_KEY", None), "groq_strategy"),
        (getattr(settings, "GROQ_ANALYST_KEY", None), "groq_analyst"),
        (getattr(settings, "GROQ_NAMING_KEY", None), "groq_naming"),
    ]
    return [(k.get_secret_value(), label) for k, label in key_map if k is not None]


def _get_brand_book_keys() -> list[tuple[str, str]]:
    """Return dedicated Gemini brand book keys (fallback only)."""
    key_map = [
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_1", None), "brand_book_1"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_2", None), "brand_book_2"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_3", None), "brand_book_3"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_4", None), "brand_book_4"),
    ]
    return [(k.get_secret_value(), label) for k, label in key_map if k is not None]


def _build_groq_llm(key_value: str) -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=8000,
        api_key=key_value,
    )


def _build_gemini_llm(key_value: str, model: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=0.7,
        google_api_key=key_value,
    )


async def _try_generate(llm, brand_name, identity, analysis, strategy, naming, visual):
    from nodes.brand_book_node import brand_book_node
    return await brand_book_node(
        brand_name=brand_name,
        identity=identity,
        analysis=analysis,
        strategy=strategy,
        naming=naming,
        visual=visual,
        llm=llm,
    )


class BrandBookAgent:
    def __init__(self):
        self.groq_keys = _get_groq_keys()
        self.gemini_keys = _get_brand_book_keys()
        if not self.groq_keys and not self.gemini_keys:
            raise RuntimeError("No Groq or Gemini brand book keys configured.")
        logger.info(
            f"Initializing Brand Book Agent "
            f"({len(self.groq_keys)} Groq keys, {len(self.gemini_keys)} Gemini keys)."
        )

    async def generate(
        self,
        brand_name: str,
        identity,
        analysis,
        strategy,
        naming,
        visual,
        research_report: str = "",
        output_dir=None,
    ) -> str:
        logger.info(f"Brand Book Agent: generating for '{brand_name}'.")

        # ── Primary: Groq ──────────────────────────────────────────────────
        for key_value, label in self.groq_keys:
            try:
                llm = _build_groq_llm(key_value)
                logger.info(f"Trying Groq llama-3.3-70b ({label}).")
                path = await _try_generate(llm, brand_name, identity, analysis, strategy, naming, visual)
                logger.info(f"Brand Book Agent complete with Groq ({label}). Output: {path}")
                return path
            except Exception as e:
                if _is_quota_error(e):
                    logger.warning(f"Groq ({label}) rate limited. Trying next key.")
                    continue
                logger.warning(f"Groq ({label}) failed: {str(e)[:100]}. Trying next key.")
                continue

        logger.warning("All Groq keys exhausted/failed. Falling back to Gemini.")

        # ── Fallback: Gemini Pro → Flash ─────────────────────────────────────
        pro_model = settings.GEMINI_MODEL_PRO
        flash_model = settings.GEMINI_MODEL

        for model in (pro_model, flash_model):
            for key_value, label in self.gemini_keys:
                try:
                    llm = _build_gemini_llm(key_value, model)
                    logger.info(f"Trying {model} ({label}).")
                    path = await _try_generate(llm, brand_name, identity, analysis, strategy, naming, visual)
                    logger.info(f"Brand Book Agent complete with {model} ({label}). Output: {path}")
                    return path
                except Exception as e:
                    if _is_quota_error(e):
                        logger.warning(f"{model} ({label}) quota exhausted. Trying next key.")
                        continue
                    raise

        raise RuntimeError(
            "Brand book generation failed — all Groq and Gemini keys exhausted."
        )