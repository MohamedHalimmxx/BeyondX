"""Visual Identity Node — generates color palette, typography, and logo concepts.

Key separation:
  Stage 6 text (visual brief) → GEMINI_VISUAL_KEY_1/2/3
  Stage 6 image (logos)       → GEMINI_LOGO_KEY_1/2/3
  Stage 7 (brand book)        → GEMINI_BRAND_BOOK_KEY_1/2/3/4 (handled by brand_book_agent.py)

Logo generation pipeline (5 Principles of Prompting applied):
  Step 1 — Visual brief: colors, typography, logo seed prompt (Gemini Flash text)
  Step 2 — Divide Labor: LLM generates 3 brand-specific logo concept descriptions
  Step 3 — Specify Format + Give Direction: build image prompt per concept
  Step 4 — Generate: Gemini Flash image (logo keys) → HuggingFace FLUX fallback
"""

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from config.settings import settings

logger = logging.getLogger("research_agent.nodes.visual_identity_node")


# ── Output schema ─────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]', text))


async def _get_franco_arabic(brand_name: str, client) -> str:
    prompt = f"""Transliterate this Arabic brand name to Franco Arabic (Arabizi).

Franco Arabic rules:
- Use Latin letters to represent Arabic sounds
- Use numbers for sounds without Latin equivalents: ع=3, ح=7, خ=5, ق=2, غ=8, ط=6
- Keep it short, readable, and brand-friendly
- Aim for 1-3 syllables — must look good as a logo wordmark
- Capitalize first letter

Brand name: {brand_name}

Return ONLY the Franco Arabic result — nothing else. No explanation, no punctuation."""

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        franco = response.text.strip().split("\n")[0].strip()
        logger.info(f"Franco Arabic: '{brand_name}' → '{franco}'")
        return franco
    except Exception as e:
        logger.warning(f"Franco Arabic transliteration failed: {e}. Using original name.")
        return brand_name


def _spell_out(name: str) -> str:
    return " – ".join(list(name))


def _clean_json(raw: str) -> str:
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return raw[start:end]


def _clean_json_array(raw: str) -> str:
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON array found in response")
    return raw[start:end]


QUOTA_ERRORS = ("RESOURCE_EXHAUSTED", "429", "QUOTA", "UNAVAILABLE", "PERMISSION_DENIED")


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).upper()
    return any(q in msg for q in QUOTA_ERRORS)


def _build_genai_clients(key_attrs: list[str]) -> list[tuple]:
    """Build Gemini clients from a list of settings attribute names."""
    try:
        import google.genai as genai
    except ImportError:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    clients = []
    for attr in key_attrs:
        key = getattr(settings, attr, None)
        if key:
            try:
                clients.append((genai.Client(api_key=key.get_secret_value()), attr))
            except Exception:
                pass
    return clients


# ── Stage 6 text clients (visual brief) ──────────────────────────────────────

def _get_visual_brief_clients() -> list[tuple]:
    """Keys dedicated to Stage 6 visual brief (Flash text)."""
    clients = _build_genai_clients([
        "GEMINI_VISUAL_KEY_1",
        "GEMINI_VISUAL_KEY_2",
        "GEMINI_VISUAL_KEY_3",
    ])
    if not clients:
        # Fallback to legacy keys
        logger.warning("No dedicated visual keys — falling back to legacy keys.")
        clients = _build_genai_clients([
            "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5",
            "GEMINI_API_KEY_6", "GEMINI_API_KEY", "GEMINI_API_KEY_2",
        ])
    return clients


# ── Stage 6 image clients (logos) ────────────────────────────────────────────

def _get_logo_clients() -> list[tuple]:
    """Keys dedicated to Stage 6 logo image generation (Flash image)."""
    clients = _build_genai_clients([
        "GEMINI_LOGO_KEY_1",
        "GEMINI_LOGO_KEY_2",
        "GEMINI_LOGO_KEY_3",
    ])
    if not clients:
        # Fallback to legacy keys
        logger.warning("No dedicated logo keys — falling back to legacy keys.")
        clients = _build_genai_clients([
            "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5",
            "GEMINI_API_KEY_6", "GEMINI_API_KEY_7", "GEMINI_API_KEY_8",
            "GEMINI_API_KEY", "GEMINI_API_KEY_2",
        ])
    return clients


# ── HuggingFace fallback ──────────────────────────────────────────────────────

async def _generate_logo_huggingface(prompt: str, filepath: Path) -> bool:
    import httpx

    hf_keys = [
        getattr(settings, "HF_API_KEY", None),
        getattr(settings, "HF_API_KEY_2", None),
    ]
    for hf_key in hf_keys:
        if not hf_key:
            continue
        try:
            logger.info("Trying HuggingFace FLUX.1-schnell (fal-ai)...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://router.huggingface.co/fal-ai/fal-ai/flux/schnell",
                    headers={
                        "Authorization": f"Bearer {hf_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={"prompt": prompt},
                )
                resp.raise_for_status()
                data = resp.json()

                image_url = data["images"][0]["url"]
                img_resp = await client.get(image_url)
                img_resp.raise_for_status()
                filepath.write_bytes(img_resp.content)

            logger.info(f"HuggingFace logo saved: {filepath}")
            return True
        except Exception as e:
            logger.warning(f"HuggingFace request failed: {e}. Trying next key.")
            continue
    return False
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

    prompt = f"""You are a senior brand designer at Pentagram — the world's most respected branding agency.

You have been handed a brand brief. Generate a complete visual identity specification.

BRAND NAME: {brand_name}
TAGLINE: {tagline}
POSITIONING: {positioning}
PERSONALITY: {', '.join(personality_traits)}
BRAND VOICE: {', '.join(brand_voice[:3])}
CORE VALUES: {', '.join(core_values[:3])}
MISSION: {mission}

Your job:
1. Choose 3 colors (primary, secondary, accent) that feel inevitable for this brand — not generic industry defaults
2. Choose 2 Google Fonts that express the brand personality through typography
3. Write a logo seed prompt that captures the brand's visual world

Return ONLY valid JSON — no markdown, no explanation:
{{
  "brand_name": "{brand_name}",
  "visual_direction": "2-3 sentence mood, aesthetic, and style summary specific to this brand",
  "colors": [
    {{"name": "evocative color name", "hex": "#XXXXXX", "role": "primary", "rationale": "why this color fits this brand specifically", "usage": "where and how to apply"}},
    {{"name": "evocative color name", "hex": "#XXXXXX", "role": "secondary", "rationale": "why it complements the primary", "usage": "where and how to apply"}},
    {{"name": "evocative color name", "hex": "#XXXXXX", "role": "accent", "rationale": "why it works as an accent", "usage": "sparingly — where"}}
  ],
  "typography": {{
    "primary_font": "Font Name",
    "primary_font_role": "Headlines and brand name",
    "primary_font_url": "https://fonts.google.com/specimen/Font+Name",
    "secondary_font": "Font Name",
    "secondary_font_role": "Body text and UI",
    "secondary_font_url": "https://fonts.google.com/specimen/Font+Name",
    "pairing_rationale": "why these two fonts express this brand's personality"
  }},
  "logo_prompt": "detailed visual world description for this brand's logo — style, mood, visual language",
  "logo_negative_prompt": "elements that would make this logo wrong for the brand"
}}"""

    text_clients = _get_visual_brief_clients()
    last_error = None

    for client, label in text_clients:
        try:
            logger.info(f"Generating visual brief with Gemini ({label}).")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            data = json.loads(_clean_json(response.text))
            return VisualIdentityOutput(**data)
        except Exception as e:
            logger.warning(f"Gemini {label} failed for visual brief: {e}")
            last_error = e

    raise RuntimeError(f"All Gemini visual clients failed for visual brief: {last_error}")


# ── Step 2: Logo concepts ─────────────────────────────────────────────────────

async def _generate_logo_concepts(
    brand_name: str,
    display_name: str,
    visual_output: VisualIdentityOutput,
    personality_traits: list[str],
    client,
) -> list[dict]:
    text_rule = (
        f"CRITICAL TEXT RULE: Every logo concept MUST include the display name spelled EXACTLY as: '{display_name}'\n"
        f"Letter by letter: {_spell_out(display_name)}\n"
        f"This exact spelling must appear in every image_generation_prompt you write.\n"
        + (f"Note: '{display_name}' is the Franco Arabic (Arabizi) version of the Arabic brand name '{brand_name}'."
           if display_name != brand_name else "")
    )

    prompt = f"""You are the creative director at Collins, the agency behind Spotify, Dropbox, and Facebook's rebrands.

You are designing 3 logo concepts for this brand:

BRAND: {brand_name}
VISUAL DIRECTION: {visual_output.visual_direction}
PRIMARY COLOR: {visual_output.colors[0].hex} ({visual_output.colors[0].name})
SECONDARY COLOR: {visual_output.colors[1].hex} ({visual_output.colors[1].name})
ACCENT: {visual_output.colors[2].hex} ({visual_output.colors[2].name})
PERSONALITY: {', '.join(personality_traits)}
LOGO SEED: {visual_output.logo_prompt}

{text_rule}

Generate 3 COMPLETELY DIFFERENT logo concepts. Approaches: wordmark, lettermark, icon+wordmark, abstract_symbol, monogram, pictorial_mark, emblem

Return ONLY valid JSON array:
[
  {{
    "concept_name": "short name for this concept",
    "approach": "wordmark|lettermark|icon_wordmark|abstract_symbol|monogram|pictorial_mark|emblem",
    "design_rationale": "why this approach fits this brand's personality",
    "real_world_reference": "real logo this shares design DNA with and why",
    "image_generation_prompt": "complete, detailed, specific prompt for AI image generation"
  }}
]"""

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        concepts = json.loads(_clean_json_array(response.text))
        logger.info(f"Generated {len(concepts)} brand-specific logo concepts.")
        return concepts[:3]
    except Exception as e:
        logger.warning(f"Logo concept generation failed: {e}. Using seed prompt fallback.")
        return [
            {"concept_name": f"Concept {i+1}", "approach": "icon_wordmark",
             "image_generation_prompt": visual_output.logo_prompt,
             "real_world_reference": "modern brand design"}
            for i in range(3)
        ]


# ── Step 3: Build image prompt ────────────────────────────────────────────────

def _build_image_prompt(
    brand_name: str,
    display_name: str,
    concept: dict,
    visual_output: VisualIdentityOutput,
) -> tuple[str, str]:
    base_prompt = concept.get("image_generation_prompt", visual_output.logo_prompt)
    primary_hex = visual_output.colors[0].hex
    secondary_hex = visual_output.colors[1].hex
    spelled = _spell_out(display_name)

    positive = (
        f"{base_prompt}, "
        f"logo text reads exactly '{display_name}' (spelled: {spelled}), "
        f"brand name '{display_name}' in clean legible typography, "
        f"color palette: {primary_hex} and {secondary_hex}, "
        f"professional logo design, vector art style, clean lines, "
        f"scalable, white background, "
        f"award-winning brand identity, Behance portfolio quality, "
        f"inspired by {concept.get('real_world_reference', 'modern brand design')}"
    )
    negative = (
        f"{visual_output.logo_negative_prompt}, "
        f"misspelled brand name, wrong letters, text artifacts, illegible text, "
        f"reversed characters, distorted typography, extra letters, missing letters, "
        f"Arabic script, RTL text, "
        f"photorealistic, stock photo, busy, cluttered, watermark, "
        f"low quality, blurry, multiple logos, drop shadow abuse, clip art"
    )
    return positive, negative


# ── Step 4: Generate single logo ─────────────────────────────────────────────

async def _generate_single_logo(
    positive_prompt: str,
    negative_prompt: str,
    filepath: Path,
    logo_clients: list,
    concept_num: int,
    total: int,
) -> bool:
    # Try HuggingFace FLUX first — fast and has working free tier
    logger.info(f"Generating logo {concept_num}/{total} with HuggingFace FLUX...")
    if await _generate_logo_huggingface(positive_prompt, filepath):
        return True

    # Fallback to Gemini if HF fails
    logger.info(f"HuggingFace failed for logo {concept_num} — trying Gemini fallback...")
    for client, label in logo_clients:
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=settings.GEMINI_IMAGE_MODEL,
                contents=positive_prompt,
                config={"response_modalities": ["Text", "Image"]},
            )
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    image_data = part.inline_data.data
                    image_bytes = base64.b64decode(image_data) if isinstance(image_data, str) else image_data
                    filepath.write_bytes(image_bytes)
                    logger.info(f"Gemini logo saved: {filepath}")
                    return True
        except Exception as e:
            if _is_quota_error(e):
                logger.warning(f"Gemini image ({label}) quota exhausted for logo {concept_num}. Trying next key.")
                continue
            logger.warning(f"Gemini image ({label}) failed for logo {concept_num}: {str(e)[:100]}")
            continue

    return False


# ── Main logo generation pipeline ────────────────────────────────────────────

async def _generate_logo_images(
    visual_output: VisualIdentityOutput,
    brand_name: str,
    personality_traits: list[str],
    output_dir: Path,
    num_images: int = 3,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get clients for text (concept generation) and image (logo rendering)
    text_clients = _get_visual_brief_clients()
    logo_clients = _get_logo_clients()

    is_arabic = _has_arabic(brand_name)
    if is_arabic and text_clients:
        display_name = await _get_franco_arabic(brand_name, text_clients[0][0])
        logger.info(f"Arabic brand name '{brand_name}' → using Franco Arabic '{display_name}' in logos.")
    else:
        display_name = brand_name

    # Step 2 — Generate brand-specific concept descriptions
    concept_client = text_clients[0][0] if text_clients else None
    if concept_client:
        concepts = await _generate_logo_concepts(
            brand_name=brand_name,
            display_name=display_name,
            visual_output=visual_output,
            personality_traits=personality_traits,
            client=concept_client,
        )
    else:
        concepts = [
            {"concept_name": f"Concept {i+1}", "approach": "icon_wordmark",
             "image_generation_prompt": visual_output.logo_prompt,
             "real_world_reference": "modern brand design"}
            for i in range(num_images)
        ]

    saved_paths = []

    for i, concept in enumerate(concepts[:num_images]):
        safe_name = brand_name.lower().replace(" ", "_")
        filepath = output_dir / f"logo_concept_{i+1}_{safe_name}.png"

        positive_prompt, negative_prompt = _build_image_prompt(
            brand_name=brand_name,
            display_name=display_name,
            concept=concept,
            visual_output=visual_output,
        )

        logger.info(f"Logo {i+1} concept: {concept.get('concept_name', '')} ({concept.get('approach', '')})")

        success = await _generate_single_logo(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            filepath=filepath,
            logo_clients=logo_clients,
            concept_num=i + 1,
            total=num_images,
        )

        if success:
            saved_paths.append(str(filepath))
        else:
            logger.warning(f"Logo concept {i+1} skipped — all providers failed.")

        if i < num_images - 1:
            logger.info("Waiting 15s before next logo concept...")
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

    logger.info("Step 1: Generating color palette, typography, and logo seed prompt.")
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

    logger.info("Step 2-4: Generating logo concepts and images.")
    try:
        logo_paths = await _generate_logo_images(
            visual_output=visual_output,
            brand_name=brand_name,
            personality_traits=identity.personality_traits,
            output_dir=output_dir,
        )
        visual_output.logo_paths = logo_paths
        logger.info(f"Visual Identity Node complete. {len(logo_paths)} logo concepts saved.")
    except Exception as e:
        logger.warning(f"Logo generation failed: {e}. Returning visual brief without images.")
        visual_output.logo_paths = []

    return visual_output