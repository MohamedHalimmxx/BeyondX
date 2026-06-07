"""Brand Book Agent — Stage 7

Rotation strategy:
  - Try gemini-2.5-pro on each key in order (keys 3, 4, 5, 1, 2)
  - If a key hits quota (429) move to the next key
  - If all Pro keys exhausted, fall back to gemini-2.5-flash on each key
  - Raises only if everything is exhausted

This gives up to 5 x 25 = 125 Pro brand book generations per day for free.
"""

import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings

logger = logging.getLogger("research_agent.agents.brand_book_agent")

QUOTA_ERRORS = ("RESOURCE_EXHAUSTED", "429", "quota")


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).upper()
    return any(q in msg for q in ("RESOURCE_EXHAUSTED", "429", "QUOTA"))


def _get_all_keys() -> list[tuple[str, str]]:
    key_map = [
        (settings.GEMINI_API_KEY_3, "key3"),
        (settings.GEMINI_API_KEY_4, "key4"),
        (settings.GEMINI_API_KEY_5, "key5"),
        (getattr(settings, "GEMINI_API_KEY_6", None), "key6"),
        (getattr(settings, "GEMINI_API_KEY_7", None), "key7"),
        (getattr(settings, "GEMINI_API_KEY_8", None), "key8"),
        (settings.GEMINI_API_KEY, "key1"),
        (settings.GEMINI_API_KEY_2, "key2"),
    ]
    return [
        (k.get_secret_value(), label)
        for k, label in key_map
        if k is not None
    ]


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
        self.keys = _get_all_keys()
        if not self.keys:
            raise RuntimeError("No Gemini API keys configured.")
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

        pro_model = settings.GEMINI_MODEL_PRO    # gemini-2.5-pro
        flash_model = settings.GEMINI_MODEL       # gemini-2.5-flash

        # Pass 1: try Pro on every key
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
                # Non-quota error — re-raise immediately
                raise

        logger.warning(f"All {pro_model} keys exhausted. Falling back to {flash_model}.")

        # Pass 2: try Flash on every key
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
            "Brand book generation failed — all Gemini Pro and Flash keys are quota-exhausted. "
            "Try again tomorrow or add more API keys."
        )