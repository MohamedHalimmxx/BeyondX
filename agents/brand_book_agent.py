"""Brand Book Agent — Stage 7

Uses dedicated GEMINI_BRAND_BOOK_KEY_1/2/3/4 keys exclusively.
These keys are separate from Stage 6 keys so Pro quota is never
competed with visual brief or logo generation.

Rotation strategy:
  Pass 1: try gemini-2.5-pro on all 4 brand book keys
  Pass 2: fallback to gemini-2.5-flash on all 4 brand book keys
  Raises only if everything exhausted.
"""

import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings

logger = logging.getLogger("research_agent.agents.brand_book_agent")


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).upper()
    return any(q in msg for q in ("RESOURCE_EXHAUSTED", "429", "QUOTA"))


def _get_brand_book_keys() -> list[tuple[str, str]]:
    """Return dedicated brand book keys only."""
    key_map = [
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_1", None), "brand_book_1"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_2", None), "brand_book_2"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_3", None), "brand_book_3"),
        (getattr(settings, "GEMINI_BRAND_BOOK_KEY_4", None), "brand_book_4"),
    ]
    keys = [
        (k.get_secret_value(), label)
        for k, label in key_map
        if k is not None
    ]
    if not keys:
        # Fallback to legacy keys if dedicated ones not set
        logger.warning("No dedicated brand book keys found — falling back to legacy Gemini keys.")
        legacy_map = [
            (getattr(settings, "GEMINI_API_KEY_3", None), "key3"),
            (getattr(settings, "GEMINI_API_KEY_4", None), "key4"),
            (getattr(settings, "GEMINI_API_KEY_5", None), "key5"),
            (getattr(settings, "GEMINI_API_KEY_6", None), "key6"),
            (getattr(settings, "GEMINI_API_KEY_7", None), "key7"),
            (getattr(settings, "GEMINI_API_KEY_8", None), "key8"),
            (getattr(settings, "GEMINI_API_KEY", None), "key1"),
            (getattr(settings, "GEMINI_API_KEY_2", None), "key2"),
        ]
        keys = [(k.get_secret_value(), label) for k, label in legacy_map if k is not None]
    return keys


def _build_llm(key_value: str, model: str) -> ChatGoogleGenerativeAI:
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
        self.keys = _get_brand_book_keys()
        if not self.keys:
            raise RuntimeError("No Gemini brand book keys configured.")
        logger.info(f"Initializing Brand Book Agent ({len(self.keys)} keys available).")

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

        pro_model   = settings.GEMINI_MODEL_PRO  # gemini-2.5-pro
        flash_model = settings.GEMINI_MODEL       # gemini-2.5-flash

        # Pass 1: try Pro on every brand book key
        for key_value, label in self.keys:
            try:
                llm = _build_llm(key_value, pro_model)
                logger.info(f"Trying {pro_model} ({label}).")
                path = await _try_generate(llm, brand_name, identity, analysis, strategy, naming, visual)
                logger.info(f"Brand Book Agent complete with {pro_model} ({label}). Output: {path}")
                return path
            except Exception as e:
                if _is_quota_error(e):
                    logger.warning(f"{pro_model} ({label}) quota exhausted. Trying next key.")
                    continue
                raise

        logger.warning(f"All {pro_model} keys exhausted. Falling back to {flash_model}.")

        # Pass 2: try Flash on every brand book key
        for key_value, label in self.keys:
            try:
                llm = _build_llm(key_value, flash_model)
                logger.info(f"Trying {flash_model} ({label}).")
                path = await _try_generate(llm, brand_name, identity, analysis, strategy, naming, visual)
                logger.info(f"Brand Book Agent complete with {flash_model} ({label}). Output: {path}")
                return path
            except Exception as e:
                if _is_quota_error(e):
                    logger.warning(f"{flash_model} ({label}) quota exhausted. Trying next key.")
                    continue
                raise

        raise RuntimeError(
            "Brand book generation failed — all brand book keys exhausted. "
            "Try again tomorrow or add more GEMINI_BRAND_BOOK_KEY_* keys."
        )