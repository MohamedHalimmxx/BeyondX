"""Visual Identity Node — generates color palette, typography, and logo concepts via Gemini + HuggingFace fallback."""

import asyncio
import base64
import logging
import json
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


# ── Gemini clients ────────────────────────────────────────────────────────────

def _get_gemini_clients():
    try:
        import google.genai as genai
    except ImportError:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    clients = []
    key1 = settings.GEMINI_API_KEY
    if key1:
        clients.append(genai.Client(api_key=key1.get_secret_value()))

    key2 = getattr(settings, "GEMINI_API_KEY_2", None)
    if key2:
        clients.append(genai.Client(api_key=key2.get_secret_value()))

    return clients


def _clean_json(raw: str) -> str:
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return raw[start:end]


# ── HuggingFace logo generation ───────────────────────────────────────────────

async def _generate_logo_huggingface(
    prompt: str,
    filepath: Path,
) -> bool:
    """Generate a single logo image via HuggingFace FLUX.1-schnell. Returns True on success."""
    hf_key = getattr(settings, "HF_API_KEY", None)
    if not hf_key:
        logger.warning("HF_API_KEY not set — skipping HuggingFace fallback.")
        return False

    try:
        from huggingface_hub import InferenceClient

        logger.info("Trying HuggingFace FLUX.1-schnell (fal-ai provider)...")

        def _generate():
            client = InferenceClient(
                provider="fal-ai",
                api_key=hf_key.get_secret_value(),
            )
            return client.text_to_image(
                prompt,
                model="black-forest-labs/FLUX.1-schnell",
            )

        image = await asyncio.to_thread(_generate)
        image.save(str(filepath))
        logger.info(f"HuggingFace logo saved: {filepath}")
        return True

    except Exception as e:
        logger.warning(f"HuggingFace request failed: {e}")
        return False


# ── Step 1: Visual brief — uses KEY 1 for text ───────────────────────────────

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

    # KEY 1 only for text — preserve KEY 2 quota for images
    clients = _get_gemini_clients()
    last_error = None

    for i, client in enumerate(clients[:1]):  # only key 1
        try:
            logger.info("Generating visual brief with Gemini key 1 (text).")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            raw = response.text
            data = json.loads(_clean_json(raw))
            return VisualIdentityOutput(**data)
        except Exception as e:
            logger.warning(f"Gemini key 1 failed for visual brief: {e}")
            last_error = e

    # fallback to key 2 for text if key 1 fails
    if len(clients) > 1:
        try:
            logger.info("Falling back to Gemini key 2 for visual brief text.")
            response = await asyncio.to_thread(
                clients[1].models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            raw = response.text
            data = json.loads(_clean_json(raw))
            return VisualIdentityOutput(**data)
        except Exception as e:
            logger.warning(f"Gemini key 2 also failed for visual brief: {e}")
            last_error = e

    raise RuntimeError(f"All Gemini clients failed for visual brief: {last_error}")


# ── Step 2: Logo images — Gemini first, HuggingFace fallback ─────────────────

async def _generate_logo_images(
    visual_output: VisualIdentityOutput,
    brand_name: str,
    output_dir: Path,
    num_images: int = 3,
) -> list[str]:

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    all_clients = _get_gemini_clients()

    # KEY 2 first for images, KEY 1 as fallback
    if len(all_clients) >= 2:
        image_clients = [all_clients[1], all_clients[0]]
    else:
        image_clients = all_clients

    style_variants = [
        f"minimalist wordmark logo, {visual_output.colors[0].hex} on white background, vector art, clean professional design",
        f"geometric icon with brand name, {visual_output.colors[0].hex} and {visual_output.colors[1].hex}, modern logo design",
        f"bold typographic logo mark, {visual_output.colors[0].hex} with {visual_output.colors[2].hex} accent, award-winning branding",
    ]

    for i, variant in enumerate(style_variants[:num_images]):
        safe_name = brand_name.lower().replace(" ", "_")
        filename = f"logo_concept_{i+1}_{safe_name}.png"
        filepath = output_dir / filename

        full_prompt = (
            f"{visual_output.logo_prompt}, {variant}, "
            f"brand name text '{brand_name}', "
            f"professional logo design, vector art, scalable, "
            f"award-winning branding, Behance portfolio quality"
        )

        gemini_success = False

        # Try Gemini first
        for j, client in enumerate(image_clients):
            try:
                logger.info(f"Generating logo {i+1}/{num_images} with Gemini image client {j+1}.")
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.GEMINI_IMAGE_MODEL,
                    contents=full_prompt,
                    config={"response_modalities": ["Text", "Image"]},
                )

                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        image_data = part.inline_data.data
                        if isinstance(image_data, str):
                            image_bytes = base64.b64decode(image_data)
                        else:
                            image_bytes = image_data
                        filepath.write_bytes(image_bytes)
                        saved_paths.append(str(filepath))
                        logger.info(f"Gemini logo saved: {filepath}")
                        gemini_success = True
                        break

                if gemini_success:
                    await asyncio.sleep(10)
                    break

            except Exception as e:
                logger.warning(f"Gemini logo {i+1} client {j+1} failed: {e}")
                if j < len(image_clients) - 1:
                    logger.info("Waiting 30s before trying next Gemini key...")
                    await asyncio.sleep(30)

        # HuggingFace fallback if Gemini failed
        if not gemini_success:
            logger.info(f"Gemini quota exhausted for logo {i+1} — trying HuggingFace FLUX...")
            hf_success = await _generate_logo_huggingface(full_prompt, filepath)
            if hf_success:
                saved_paths.append(str(filepath))
            else:
                logger.warning(f"Logo concept {i+1} skipped — both Gemini and HuggingFace failed.")

        # wait between logo attempts
        if i < num_images - 1:
            logger.info(f"Waiting 15s before next logo concept...")
            await asyncio.sleep(15)

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

    logger.info("Step 1: Generating color palette, typography, and logo prompt (Gemini key 1).")
    visual_output = await _generate_visual_brief(
        brand_name=brand_name,
        tagline=identity.tagline,
        positioning=analysis.positioning_recommendation,
        personality_traits=identity.personality_traits,
        brand_voice=identity.brand_voice_is,
        core_values=identity.core_values,
        mission=identity.mission,
    )

    logger.info("Waiting 30s before image generation...")
    await asyncio.sleep(30)

    logger.info("Step 2: Generating logo concepts (Gemini key 2 → key 1 → HuggingFace FLUX).")
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