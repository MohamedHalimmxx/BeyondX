"""Brand Identity Node — builds mission, vision, origin story, voice, and values."""

import logging
import json
from langchain_core.language_models.chat_models import BaseChatModel
from openai import RateLimitError as CerebrasRateLimitError

from state.brand_identity_state import BrandIdentityOutput
from prompts.brand_identity_prompts import (
    BRAND_IDENTITY_SYSTEM_PROMPT,
    BRAND_IDENTITY_HUMAN_TEMPLATE,
)
from utils.llm_utils import invoke_with_fallback, ALL_EXHAUSTED_MSG

logger = logging.getLogger("research_agent.nodes.brand_identity_node")


def _build_messages(
    idea: str, location: str, differentiator: str, ideal_customer: str,
    non_negotiable: str, positioning_statement: str,
    naming_output, analysis,
) -> list[dict]:
    top_names = "\n".join([
        f"{i+1}. {c.name} — {c.positioning_fit}"
        for i, c in enumerate(naming_output.candidates[:3])
    ])
    white_space = analysis.white_spaces[0].description if analysis.white_spaces else "Not identified"
    pain_points = "; ".join([p.theme for p in analysis.pain_points]) if analysis.pain_points else "Not identified"

    return [
        {"role": "system", "content": BRAND_IDENTITY_SYSTEM_PROMPT},
        {"role": "user", "content": BRAND_IDENTITY_HUMAN_TEMPLATE.format(
            idea=idea, location=location, differentiator=differentiator,
            ideal_customer=ideal_customer, non_negotiable=non_negotiable,
            positioning_statement=positioning_statement,
            top_names=top_names, white_space=white_space,
            pain_points=pain_points,
            competitive_advantage=analysis.competitive_advantage,
        )},
    ]


async def _groq_generate(llm, messages: list) -> BrandIdentityOutput:
    from typing import cast
    structured_llm = llm.with_structured_output(BrandIdentityOutput)
    return cast(BrandIdentityOutput, await structured_llm.ainvoke(messages))


async def brand_identity_node(
    idea: str,
    positioning_statement: str,
    naming_output,
    analysis,
    brand_brief,
    llm: BaseChatModel,
) -> BrandIdentityOutput:
    logger.info("Executing Brand Identity Node: Building brand foundation document.")

    messages = _build_messages(
        idea=idea, location=brand_brief.location,
        differentiator=brand_brief.differentiator,
        ideal_customer=brand_brief.ideal_customer,
        non_negotiable=brand_brief.non_negotiable,
        positioning_statement=positioning_statement,
        naming_output=naming_output, analysis=analysis,
    )

    try:
        result = await invoke_with_fallback(_groq_generate, llm, messages,
                                            cerebras_temperature=0.6)
        logger.info("Brand Identity Node complete.")
        return result
    except RuntimeError:
        pass

    # Cerebras needs explicit JSON schema
    import asyncio
    from config.llm_factory import get_cerebras_llm
    cerebras = get_cerebras_llm(temperature=0.6)
    cerebras_messages = [
        {
            "role": "system",
            "content": BRAND_IDENTITY_SYSTEM_PROMPT + (
                "\n\nReturn ONLY valid JSON. No markdown. Exact schema:\n"
                '{"selected_name":"","name_rationale":"","mission":"","vision":"",'
                '"origin_story":"","brand_promise":"","personality_traits":[],'
                '"brand_voice_is":[],"brand_voice_never":[],"core_values":[],"tagline":""}'
            ),
        },
        messages[1],
    ]
    for attempt in range(3):
        try:
            response = await cerebras.ainvoke(cerebras_messages)
            raw = response.content.replace("```json", "").replace("```", "").strip()
            start, end = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            result = BrandIdentityOutput(**data)
            logger.info("Brand Identity Node complete via Cerebras.")
            return result
        except CerebrasRateLimitError:
            wait = (attempt + 1) * 15
            logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
            await asyncio.sleep(wait)
        except Exception as err:
            logger.warning(f"Cerebras brand identity parse failed: {err}. Retrying.")
            await asyncio.sleep(10)
    raise RuntimeError(ALL_EXHAUSTED_MSG)