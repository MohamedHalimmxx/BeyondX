"""
Brand Experience Node — Stage 7

Generates ONE premium single-page HTML experience that serves both
investors and target customers simultaneously.

The LLM makes all design decisions based on brand personality.
Structure is fixed (8 elements). Design is entirely brand-driven.

Pipeline:
  1. Serialize all pipeline data as a creative brief narrative
  2. Gemini 2.5 Pro generates the complete HTML experience
  3. Node embeds base64 logo images
  4. Saves self-contained HTML file
"""

import base64
import logging
from pathlib import Path

logger = logging.getLogger("research_agent.nodes.brand_book_node")


# ── Context Serializer ────────────────────────────────────────────────────────

def _serialize_brand_context(brand_name, identity, analysis, strategy, naming, visual) -> str:
    """
    Serialize all pipeline outputs as a creative brief narrative.
    Not a data dump — a story a senior designer would read before starting work.
    """

    traits        = getattr(identity, 'personality_traits', [])
    voice_is      = getattr(identity, 'brand_voice_is', [])
    voice_never   = getattr(identity, 'brand_voice_never', [])
    values        = getattr(identity, 'core_values', [])
    tagline       = getattr(identity, 'tagline', '')
    mission       = getattr(identity, 'mission', '')
    vision        = getattr(identity, 'vision', '')
    promise       = getattr(identity, 'brand_promise', '')
    origin        = getattr(identity, 'origin_story', '')

    colors        = getattr(visual, 'colors', [])
    typography    = getattr(visual, 'typography', None)
    visual_dir    = getattr(visual, 'visual_direction', '')
    logo_count    = len(getattr(visual, 'logo_paths', []))

    axes          = getattr(analysis, 'positioning_axes', None)
    competitors   = getattr(analysis, 'competitors', [])
    white_spaces  = getattr(analysis, 'white_spaces', [])
    pain_points   = getattr(analysis, 'pain_points', [])
    positioning   = getattr(analysis, 'positioning_recommendation', '')
    target        = getattr(analysis, 'target_audience_summary', '')
    advantage     = getattr(analysis, 'competitive_advantage', '')

    tagline_gtm   = ''
    hooks         = []
    channels      = []
    phases        = []
    moat          = ''
    if hasattr(strategy, 'messaging_framework'):
        tagline_gtm = getattr(strategy.messaging_framework, 'primary_tagline', '')
        hooks       = getattr(strategy.messaging_framework, 'value_prop_hooks', [])
    if hasattr(strategy, 'channel_matrix'):
        channels    = strategy.channel_matrix
    if hasattr(strategy, 'ninety_day_launch_roadmap'):
        phases      = strategy.ninety_day_launch_roadmap
    if hasattr(strategy, 'defensive_moat_strategy'):
        moat        = strategy.defensive_moat_strategy

    top_name       = getattr(naming, 'top_recommendation', brand_name)
    naming_strategy_text = getattr(naming, 'naming_strategy', '')
    candidates     = [c for c in getattr(naming, 'candidates', [])
                      if getattr(c, 'brand_conflict', '') != 'conflict'][:4]

    brief = f"""# BRAND CREATIVE BRIEF — {brand_name}

## THE BRAND PERSONALITY

{brand_name} is not a generic product. It has a specific worldview.

**Tagline:** {tagline}
**Mission:** {mission}
**Vision:** {vision}
**Promise:** {promise}

**Personality:** {', '.join(traits)}
**Voice — how it talks:** {', '.join(voice_is)}
**Voice — how it NEVER talks:** {', '.join(voice_never)}
**Values:** {', '.join(values)}

**Origin Story:**
{origin[:1000]}

---

## VISUAL IDENTITY (use exactly as specified)

**Visual direction:** {visual_dir}

**Colors:**"""

    for c in colors:
        brief += f"\n  {c.name} {c.hex} [{c.role.upper()}] — {c.rationale} | Use: {c.usage}"

    if typography:
        brief += f"""

**Typography:**
  Headlines: {typography.primary_font} — {typography.primary_font_role}
  Body: {typography.secondary_font} — {typography.secondary_font_role}
  Why this pairing: {typography.pairing_rationale}"""

    brief += f"""
  Logo concepts available: {logo_count} (embed using {{{{LOGO_1}}}}, {{{{LOGO_2}}}}, {{{{LOGO_3}}}})

---

## THE MARKET REALITY

**Who wins here:** {positioning}
**Who we serve:** {target}
**Why we win:** {advantage}"""

    if axes:
        brief += f"""
**Competitive axes:**
  X-axis: {axes.axis_1_label} ({axes.axis_1_low} → {axes.axis_1_high})
  Y-axis: {axes.axis_2_label} ({axes.axis_2_low} → {axes.axis_2_high})"""

    if competitors:
        brief += "\n\n**Competitors (for the positioning chart):**"
        for c in competitors[:6]:
            brief += f"\n  {c.name}: x={c.axis_1_score}, y={c.axis_2_score}"
            if c.top_weaknesses:
                brief += f" | weakness: {c.top_weaknesses[0]}"

    if white_spaces:
        brief += "\n\n**The gap we fill:**"
        for ws in white_spaces[:2]:
            brief += f"\n  {ws.description} — {ws.why_it_exists}"

    if pain_points:
        brief += "\n\n**Customer pain points we solve:**"
        for pp in pain_points[:3]:
            brief += f"\n  [{pp.theme}] {pp.description} → {pp.opportunity}"

    brief += f"""

---

## GO-TO-MARKET

**Launch line:** {tagline_gtm or tagline}

**Value hooks (use these verbatim in the page copy):**"""
    for h in hooks[:3]:
        brief += f"\n  — {h}"

    if channels:
        brief += "\n\n**Primary channels:**"
        for ch in channels[:3]:
            brief += f"\n  {ch.channel_name} ({ch.allocation_weight})"

    if phases:
        brief += "\n\n**90-day roadmap:**"
        for i, phase in enumerate(phases[:3]):
            brief += f"\n  Phase {i+1}: {phase.phase_name} — {phase.strategic_objective}"

    if moat:
        brief += f"\n\n**Defensive moat:** {moat[:200]}"

    brief += f"""

---

## NAMING

**Selected name:** {top_name}
**Strategy:** {naming_strategy_text}
**Other candidates considered:**"""
    for c in candidates[:3]:
        com = getattr(c, 'domain_com', '')
        brief += f"\n  {c.name} (score: {c.score:.1f}, .com: {com})"

    return brief


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the creative director and lead developer at the agency behind Linear.app, Stripe.com, and Airbnb's digital brand presence.

You have been handed a brand creative brief. Your job is to build ONE premium single-page HTML experience that tells this brand's complete story.

═══════════════════════════════════════════════════
THIS PAGE HAS TWO AUDIENCES SIMULTANEOUSLY
═══════════════════════════════════════════════════

INVESTORS — they need to see a credible, well-positioned brand with a real market opportunity and a clear path to winning.

TARGET CUSTOMERS — they need to feel this brand was built for them and want to sign up immediately.

The best brand pages serve both at once. Stripe's homepage makes a developer want to build AND makes a VC want to invest. That is the standard.

═══════════════════════════════════════════════════
MANDATORY TECHNICAL REQUIREMENTS
═══════════════════════════════════════════════════

- Single self-contained HTML file — ALL CSS inside <style>, ALL JS inside <script>
- Load Google Fonts via CDN using the EXACT fonts specified in the brief
- Chart.js 4.4.1 from https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js
- CSS custom properties for ALL brand colors (--color-primary, --color-secondary, --color-accent, --color-bg, --color-text)
- Intersection Observer API for scroll-triggered fade and slide animations
- Smooth scroll behavior on the entire page
- CSS Grid and Flexbox — no table layouts, no float layouts
- All hover states: smooth transitions (0.25s ease)
- Logo placeholders: use <img src="{{LOGO_1}}">, <img src="{{LOGO_2}}">, <img src="{{LOGO_3}}">
- Responsive: looks good on both desktop and mobile

═══════════════════════════════════════════════════
REQUIRED ELEMENTS — HOW YOU DESIGN THEM IS YOUR DECISION
═══════════════════════════════════════════════════

Every brand experience needs these elements. The ORDER, LAYOUT, VISUAL TREATMENT, and COPY of each is entirely your decision based on this specific brand.

1. NAVIGATION — sticky, translucent/frosted, smooth scroll links to sections
2. HERO — brand name at display scale (80-120px), tagline, core promise, primary CTA button
3. THE PROBLEM — what is broken in this market, why existing solutions fail (from pain points data)
4. THE SOLUTION — what this brand does differently, the competitive advantage
5. MARKET POSITION — interactive Chart.js scatter plot showing competitor positions and the brand's white space. Style with brand colors. Custom tooltips. Animated on load.
6. BRAND STORY — mission, vision, origin story written in the brand's actual voice
7. VISUAL IDENTITY — color swatches (large, premium), typography specimens at real scale, logo concepts
8. GO-TO-MARKET — 90-day roadmap and channels, presented as a timeline or phased view
9. CTA — email/waitlist section with brand-specific copy (not "Subscribe"), a real styled input field, and a submit button

═══════════════════════════════════════════════════
PRINCIPLE 1 — THE DESIGN IS DRIVEN BY THE BRAND PERSONALITY
═══════════════════════════════════════════════════

Read the brand's personality traits, voice, and industry. Let them dictate every design decision.

A DEFIANT, STREET-SAVVY BRAND (fintech, disruptor, youth) →
  Heavy typography. High contrast. Attitude. Dark backgrounds. Electric accent colors.
  Short punchy sentences. No decoration. Confidence over elegance.
  Reference: FeeFree should feel like Monzo meets Cash App.

A LUXURY, HERITAGE BRAND (premium goods, artisan, cultural) →
  Generous whitespace. Serif elegance. Warm earth tones. Slow scroll.
  Long sentences. Details matter. Restraint over loudness.
  Reference: Arabesque Box should feel like Net-a-Porter meets Aesop.

A PRECISION TECH / DATA BRAND (SaaS, AI, edtech, fintech) →
  Clean grid. Monospace accents. Data visualization. White space as signal.
  Precise language. Confident numbers. Trust through evidence.
  Reference: EgyptianGrad should feel like Linear meets Duolingo.

A WELLNESS / FOOD / LIFESTYLE BRAND →
  Photography placeholders. Warm palette. Rounded forms. Human photography.
  Conversational language. Warmth. Community signals.

If you can swap the design into another brand's page without changing anything, you have failed.

═══════════════════════════════════════════════════
PRINCIPLE 2 — SPECIFY FORMAT: WHAT EXCELLENT LOOKS LIKE
═══════════════════════════════════════════════════

TYPOGRAPHY:
  - Hero headline: clamp(60px, 8vw, 120px) — never smaller
  - Section headlines: clamp(36px, 5vw, 64px)
  - Body: 18-20px, line-height 1.6-1.8
  - Letter-spacing on headlines: -0.02em to -0.04em

SPACING:
  - Sections: 120px to 180px vertical padding
  - Elements breathe — never cramped
  - Max content width: 1200-1400px, centered

ANIMATIONS:
  - Elements start opacity: 0, transform: translateY(30px)
  - Intersection Observer triggers: opacity 1, transform none, transition 0.7s ease
  - Stagger children with animation-delay
  - Chart animates on scroll into view

COLOR APPLICATION:
  - Primary color is atmosphere: use as background sections, not just text
  - Gradients between primary and secondary where appropriate
  - Accent color is precious: use for CTAs, highlights, key numbers only

INTERACTIVE CHART:
  - Scatter plot with competitor dots labeled
  - Brand's white space marked with a star or distinct marker
  - Axes labeled from the brief
  - Styled tooltips showing competitor name and scores
  - Animated entrance

CTA SECTION:
  - Full-width with brand primary color as background
  - Email input styled to match brand (not default browser input)
  - Button copy specific to this brand (not "Subscribe" or "Sign Up")
  - Supporting copy in brand voice

═══════════════════════════════════════════════════
PRINCIPLE 3 — PROVIDE EXAMPLES: WHAT BAD LOOKS LIKE
═══════════════════════════════════════════════════

NEVER DO THESE — they signal a template, not a brand:
  ✗ Plain white background with black text for entire page
  ✗ Default card style: background white, border-radius 8px, box-shadow 0 2px 4px rgba(0,0,0,0.1)
  ✗ Everything center-aligned and stacked vertically in one column
  ✗ Generic marketing copy ("We are passionate about delivering innovative solutions")
  ✗ h1/h2/h3 tags at default browser sizes
  ✗ No scroll animations — elements just appear
  ✗ Color used only on text, never as background or atmosphere
  ✗ Identical section layout repeated — every section must have a distinct layout
  ✗ The competitive chart as a basic gray dots scatter plot
  ✗ CTA with placeholder text "Enter your email" and a "Submit" button

═══════════════════════════════════════════════════
COPY INSTRUCTION
═══════════════════════════════════════════════════

Write all copy in the brand's actual voice. Use the value hooks from the brief verbatim where they fit.
If the brand is defiant and direct, the copy is defiant and direct.
If the brand is warm and artisan, the copy is warm and artisan.
The origin story goes on the page as the brand would actually tell it — not as a dry summary.

Return ONLY the complete HTML file starting with <!DOCTYPE html>. No markdown fences, no explanation."""


# ── Logo Embedder ─────────────────────────────────────────────────────────────

def _embed_logos(html: str, logo_paths: list) -> str:
    """Replace {{LOGO_N}} placeholders with base64-encoded PNG data URIs."""
    for i, path in enumerate(logo_paths[:3], start=1):
        placeholder = f"{{{{LOGO_{i}}}}}"
        if placeholder not in html:
            continue
        try:
            data = Path(path).read_bytes()
            b64 = base64.b64encode(data).decode("utf-8")
            html = html.replace(placeholder, f"data:image/png;base64,{b64}")
            logger.info(f"Embedded logo {i} ({len(data)//1024}KB)")
        except Exception as e:
            logger.warning(f"Could not embed logo {i}: {e}")
            html = html.replace(placeholder, "")
    return html


# ── HTML Generator ────────────────────────────────────────────────────────────

async def _generate_html(llm, brand_context: str) -> str:
    logger.info("Brand Book Node: LLM generating brand experience HTML.")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Here is the brand creative brief. "
            f"Build the complete premium brand experience.\n\n"
            f"{brand_context}\n\n"
            f"Return ONLY the complete HTML file starting with <!DOCTYPE html>."
        )}
    ]

    response = await llm.ainvoke(messages)
    raw = response.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    if "<!DOCTYPE" not in raw and "<html" not in raw.lower():
        raise ValueError(f"LLM did not return valid HTML. Got: {raw[:200]}")

    return raw


# ── Main Node ─────────────────────────────────────────────────────────────────

async def brand_book_node(
    brand_name: str,
    identity,
    analysis,
    strategy,
    naming,
    visual,
    llm,
    research_report: str = "",
    output_dir=None,
) -> str:
    logger.info(f"Brand Book Node: Starting for '{brand_name}'.")

    if visual is None:
        raise ValueError("Visual identity required — Stage 6 did not complete.")

    # Step 1: Build creative brief
    brand_context = _serialize_brand_context(
        brand_name=brand_name,
        identity=identity,
        analysis=analysis,
        strategy=strategy,
        naming=naming,
        visual=visual,
    )

    # Step 2: Generate HTML
    html = await _generate_html(llm, brand_context)

    # Step 3: Embed logos
    logo_paths = getattr(visual, 'logo_paths', []) or []
    if logo_paths:
        html = _embed_logos(html, logo_paths)

    # Step 4: Save
    if output_dir is None:
        output_dir = Path("brand_packs") / brand_name.lower().replace(" ", "_")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "brand_experience.html"
    output_path.write_text(html, encoding="utf-8")

    size_kb = output_path.stat().st_size // 1024
    logger.info(f"Brand Book Node complete. Saved to {output_path} ({size_kb}KB)")

    return str(output_path)