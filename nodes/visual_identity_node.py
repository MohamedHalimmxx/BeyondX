"""Visual Identity Node — generates color palette, typography, and logo concepts via Gemini."""

import asyncio
import base64
import logging
import json
import time
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from config.settings import settings

logger = logging.getLogger("research_agent.nodes.visual_identity_node")


# ── State schema ─────────────────────────────────────────────────────────────

class ColorSwatch(BaseModel):
    name: str
    hex: str
    role: str = Field(..., description="primary / secondary / accent")
    rationale: str
    usage: str


class FontPairing(BaseModel):
    primary_font: str
    primary_font_role: str
    primary_font_url: str
    secondary_font: str
    secondary_font_role: str
    secondary_font_url: str
    pairing_rationale: str


class VisualIdentityOutput(BaseModel):
    brand_name: str
    visual_direction: str
    colors: list[ColorSwatch]
    typography: FontPairing
    logo_prompt: str
    logo_negative_prompt: str
    logo_paths: list[str] = Field(default_factory=list)


# ── Gemini client with fallback ───────────────────────────────────────────────

def _get_gemini_clients():
    """Return list of (api_key, client) tuples — primary then fallback."""
    try:
        import google.genai as genai
    except ImportError:
        raise ImportError(
            "google-genai package not installed. Run: pip install google-genai"
        )

    clients = []
    key1 = settings.GEMINI_API_KEY
    if key1:
        clients.append(genai.Client(api_key=key1.get_secret_value()))

    key2 = getattr(settings, "GEMINI_API_KEY_2", None)
    if key2:
        clients.append(genai.Client(api_key=key2.get_secret_value()))

    if not clients:
        raise ValueError("No Gemini API key configured. Set GEMINI_API_KEY in .env")

    return clients


def _clean_json(raw: str) -> str:
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return raw[start:end]


# ── Step 1: Visual brief ──────────────────────────────────────────────────────

async def _generate_visual_brief(
    brand_name: str,
    tagline: str,
    positioning: str,
    personality_traits: list[str],
    brand_voice: list[str],
    core_values: list[str],
    mission: str,
) -> VisualIdentityOutput:

    prompt = f"""You are a senior brand designer at a world-class branding agency.

Based on this brand brief, generate a complete visual identity specification.

BRAND NAME: {brand_name}
TAGLINE: {tagline}
POSITIONING: {positioning}
PERSONALITY TRAITS: {', '.join(personality_traits)}
BRAND VOICE: {', '.join(brand_voice[:3])}
CORE VALUES: {', '.join(core_values[:3])}
MISSION: {mission}

Generate a visual identity with:
1. Exactly 3 colors (primary, secondary, accent) with specific hex codes and psychological rationale
2. Typography pairing — 2 Google Fonts with usage rules and CDN URLs
3. A detailed logo generation prompt for an AI image model

Return ONLY valid JSON, no markdown, no explanation:
{{
  "brand_name": "{brand_name}",
  "visual_direction": "2-3 sentence mood and style summary",
  "colors": [
    {{"name": "color name", "hex": "#XXXXXX", "role": "primary", "rationale": "psychological rationale", "usage": "when and how to use"}},
    {{"name": "color name", "hex": "#XXXXXX", "role": "secondary", "rationale": "why it fits", "usage": "when and how to use"}},
    {{"name": "color name", "hex": "#XXXXXX", "role": "accent", "rationale": "why it fits", "usage": "when and how to use"}}
  ],
  "typography": {{
    "primary_font": "Font Name",
    "primary_font_role": "Headlines and brand name display",
    "primary_font_url": "https://fonts.google.com/specimen/Font+Name",
    "secondary_font": "Font Name",
    "secondary_font_role": "Body text and UI elements",
    "secondary_font_url": "https://fonts.google.com/specimen/Font+Name",
    "pairing_rationale": "why these two fonts work together for this brand"
  }},
  "logo_prompt": "detailed prompt: minimalist logo for [brand], [style], [colors], professional branding, vector art style, clean lines, award-winning design, white background",
  "logo_negative_prompt": "photorealistic, stock photo, busy, cluttered, low quality, blurry, watermark, text artifacts, multiple logos"
}}"""

    clients = _get_gemini_clients()
    last_error = None

    for i, client in enumerate(clients):
        try:
            logger.info(f"Generating visual brief with Gemini client {i+1}/{len(clients)}.")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            raw = response.text
            data = json.loads(_clean_json(raw))
            return VisualIdentityOutput(**data)
        except Exception as e:
            logger.warning(f"Gemini client {i+1} failed for visual brief: {e}")
            last_error = e
            if i < len(clients) - 1:
                await asyncio.sleep(2)

    raise RuntimeError(f"All Gemini clients failed for visual brief: {last_error}")


# ── Step 2: Logo image generation ────────────────────────────────────────────

async def _generate_logo_images(
    visual_output: VisualIdentityOutput,
    brand_name: str,
    output_dir: Path,
    num_images: int = 3,
) -> list[str]:

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    clients = _get_gemini_clients()

    style_variants = [
        f"minimalist wordmark style, {visual_output.colors[0].hex} on white background",
        f"geometric icon with wordmark, {visual_output.colors[0].hex} and {visual_output.colors[1].hex}",
        f"bold typographic mark, {visual_output.colors[0].hex} with {visual_output.colors[2].hex} accent",
    ]

    for i, variant in enumerate(style_variants[:num_images]):
        full_prompt = (
            f"{visual_output.logo_prompt}, {variant}, "
            f"brand name text '{brand_name}', "
            f"professional logo design, vector art, scalable, "
            f"award-winning branding, Behance portfolio quality, "
            f"negative: {visual_output.logo_negative_prompt}"
        )

        last_error = None
        for j, client in enumerate(clients):
            try:
                logger.info(f"Generating logo concept {i+1}/{num_images} with client {j+1}.")
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.GEMINI_IMAGE_MODEL,
                    contents=full_prompt,
                    config={"response_modalities": ["IMAGE"]},
                )

                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        image_data = part.inline_data.data
                        if isinstance(image_data, str):
                            image_bytes = base64.b64decode(image_data)
                        else:
                            image_bytes = image_data

                        safe_name = brand_name.lower().replace(" ", "_")
                        filename = f"logo_concept_{i+1}_{safe_name}.png"
                        filepath = output_dir / filename
                        filepath.write_bytes(image_bytes)
                        saved_paths.append(str(filepath))
                        logger.info(f"Saved: {filepath}")
                        break

                await asyncio.sleep(3)
                break  # success — move to next image

            except Exception as e:
                logger.warning(f"Logo {i+1} client {j+1} failed: {e}")
                last_error = e
                if j < len(clients) - 1:
                    await asyncio.sleep(5)

        if last_error and len(saved_paths) <= i:
            logger.warning(f"Logo concept {i+1} skipped after all clients failed.")

    return saved_paths


# ── Main node ─────────────────────────────────────────────────────────────────

async def visual_identity_node(
    brand_name: str,
    identity,
    analysis,
    output_dir: Optional[Path] = None,
) -> VisualIdentityOutput:
    logger.info("Executing Visual Identity Node: Generating brand visual system.")

    if output_dir is None:
        output_dir = Path("brand_packs") / brand_name.lower().replace(" ", "_")

    logger.info("Step 1: Generating color palette, typography, and logo prompt.")
    visual_output = await _generate_visual_brief(
        brand_name=brand_name,
        tagline=identity.tagline,
        positioning=analysis.positioning_recommendation,
        personality_traits=identity.personality_traits,
        brand_voice=identity.brand_voice_is,
        core_values=identity.core_values,
        mission=identity.mission,
    )

    logger.info("Step 2: Generating logo concept images via Gemini Imagen.")
    try:
        logo_paths = await _generate_logo_images(
            visual_output=visual_output,
            brand_name=brand_name,
            output_dir=output_dir,
        )
        visual_output.logo_paths = logo_paths
        logger.info(f"Visual Identity Node complete. {len(logo_paths)} logo concepts saved.")
    except Exception as e:
        logger.warning(f"Logo generation failed: {e}. Returning visual brief without images.")
        visual_output.logo_paths = []

    return visual_output