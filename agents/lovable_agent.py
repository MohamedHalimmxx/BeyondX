"""
Lovable Agent — Stage 8 (Optional)

Generates a Lovable Build-with-URL link from the full pipeline output.
When the user clicks the link, Lovable builds a production-ready
React/Vite/Tailwind web app from the brand data in ~2 minutes.

Free tier: 5 credits/day, 30/month.
No API key required — URL-based.

The prompt is engineered to produce premium results:
- Exact brand colors as CSS variables
- Exact Google Fonts specified
- Brand personality drives design language
- All sections specified with real copy from the pipeline
- Design reference matched to brand archetype
"""

import logging
import urllib.parse
import webbrowser
from pathlib import Path

logger = logging.getLogger("research_agent.agents.lovable_agent")


# ── Design reference map ───────────────────────────────────────────────────
# Maps brand personality to a Lovable-optimized design reference.
# The LLM picks the closest match based on personality traits.

DESIGN_REFERENCES = {
    "fintech_defiant":  "dark and bold like Monzo or Cash App — high contrast, electric colors, urgent typography",
    "fintech_trust":    "clean and trustworthy like Stripe or Wise — white space, precise grid, data-forward",
    "luxury":           "generous and slow like Aesop or Net-a-Porter — earth tones, serif elegance, restraint",
    "edtech":           "clear and empowering like Duolingo or Linear — friendly type, color pops, progress signals",
    "food_health":      "warm and fresh like Sweetgreen or Daily Harvest — photography-ready, rounded, approachable",
    "saas_tech":        "precise and minimal like Linear or Vercel — monospace accents, dark bg, data viz",
    "default":          "premium and modern like a top-tier startup — clean grid, bold type, intentional color",
}


def _pick_design_reference(personality_traits: list[str], industry: str) -> str:
    """Pick the most appropriate design reference based on brand personality."""
    traits_lower = " ".join(personality_traits).lower()
    industry_lower = industry.lower()

    if any(w in traits_lower for w in ["defiant", "rebel", "street", "bold", "urgent"]):
        return DESIGN_REFERENCES["fintech_defiant"]
    if any(w in traits_lower for w in ["luxury", "heritage", "artisan", "refined", "elegant"]):
        return DESIGN_REFERENCES["luxury"]
    if any(w in industry_lower for w in ["fintech", "lending", "payment", "bank", "finance"]):
        return DESIGN_REFERENCES["fintech_trust"]
    if any(w in industry_lower for w in ["education", "tutor", "learn", "study"]):
        return DESIGN_REFERENCES["edtech"]
    if any(w in industry_lower for w in ["food", "meal", "nutrition", "health", "wellness"]):
        return DESIGN_REFERENCES["food_health"]
    if any(w in industry_lower for w in ["saas", "software", "platform", "api", "tech"]):
        return DESIGN_REFERENCES["saas_tech"]
    return DESIGN_REFERENCES["default"]


def _build_lovable_prompt(
    brand_name: str,
    identity,
    analysis,
    strategy,
    naming,
    visual,
) -> str:
    """
    Build a comprehensive Lovable prompt from pipeline data.
    Up to 50,000 characters. More detail = better output.
    """

    # Identity
    tagline       = getattr(identity, 'tagline', '')
    mission       = getattr(identity, 'mission', '')
    promise       = getattr(identity, 'brand_promise', '')
    origin        = getattr(identity, 'origin_story', '')[:600]
    traits        = getattr(identity, 'personality_traits', [])
    voice_is      = getattr(identity, 'brand_voice_is', [])
    values        = getattr(identity, 'core_values', [])

    # Visual
    colors        = getattr(visual, 'colors', [])
    typography    = getattr(visual, 'typography', None)
    visual_dir    = getattr(visual, 'visual_direction', '')

    primary_color   = colors[0].hex if colors else '#000000'
    secondary_color = colors[1].hex if len(colors) > 1 else '#ffffff'
    accent_color    = colors[2].hex if len(colors) > 2 else '#0066ff'
    primary_name    = colors[0].name if colors else 'Primary'
    secondary_name  = colors[1].name if len(colors) > 1 else 'Secondary'
    accent_name     = colors[2].name if len(colors) > 2 else 'Accent'

    primary_font    = typography.primary_font if typography else 'Inter'
    secondary_font  = typography.secondary_font if typography else 'Inter'

    # Analysis
    target        = getattr(analysis, 'target_audience_summary', '')
    advantage     = getattr(analysis, 'competitive_advantage', '')
    positioning   = getattr(analysis, 'positioning_recommendation', '')
    competitors   = getattr(analysis, 'competitors', [])
    white_spaces  = getattr(analysis, 'white_spaces', [])
    pain_points   = getattr(analysis, 'pain_points', [])
    axes          = getattr(analysis, 'positioning_axes', None)

    # Strategy
    tagline_gtm = ''
    hooks = []
    channels = []
    phases = []
    moat = ''
    if hasattr(strategy, 'messaging_framework'):
        tagline_gtm = getattr(strategy.messaging_framework, 'primary_tagline', '')
        hooks       = getattr(strategy.messaging_framework, 'value_prop_hooks', [])
    if hasattr(strategy, 'channel_matrix'):
        channels    = strategy.channel_matrix[:3]
    if hasattr(strategy, 'ninety_day_launch_roadmap'):
        phases      = strategy.ninety_day_launch_roadmap[:3]
    if hasattr(strategy, 'defensive_moat_strategy'):
        moat        = strategy.defensive_moat_strategy[:150]

    design_ref = _pick_design_reference(traits, positioning)

    # Competitor data for chart
    comp_data = []
    for c in competitors[:6]:
        comp_data.append(f"{c.name} (x={c.axis_1_score}, y={c.axis_2_score})")

    axis_x = axes.axis_1_label if axes else "Price"
    axis_y = axes.axis_2_label if axes else "Quality"
    axis_x_low  = axes.axis_1_low  if axes else "Low"
    axis_x_high = axes.axis_1_high if axes else "High"
    axis_y_low  = axes.axis_2_low  if axes else "Low"
    axis_y_high = axes.axis_2_high if axes else "High"

    prompt = f"""Build a premium single-page React web application for the brand "{brand_name}".

This is a brand experience page that serves both investors and target customers simultaneously.
Design reference: {design_ref}

═══════════════════════════════════
TECH STACK REQUIREMENTS
═══════════════════════════════════
- React + Vite + TypeScript + Tailwind CSS
- Google Fonts: load "{primary_font}" for headlines and "{secondary_font}" for body text
- Recharts or Chart.js for the competitive positioning scatter chart
- Framer Motion for scroll animations (fade in, slide up)
- Lucide React for icons
- shadcn/ui components where appropriate

═══════════════════════════════════
BRAND DESIGN SYSTEM
═══════════════════════════════════
CSS Custom Properties (define in :root):
--color-primary: {primary_color};    /* {primary_name} */
--color-secondary: {secondary_color}; /* {secondary_name} */
--color-accent: {accent_color};       /* {accent_name} */

Visual direction: {visual_dir}

Typography:
- Headlines: {primary_font} — use at display scale (80-120px for hero)
- Body: {secondary_font} — 18-20px, line-height 1.6
- Letter-spacing on headlines: -0.02em

Color application rules:
- Primary as background atmosphere (gradients, section backgrounds)
- Accent ONLY for CTAs, key numbers, and highlights
- Never use default white background + black text for entire page
- Sections must alternate and breathe

═══════════════════════════════════
BRAND IDENTITY
═══════════════════════════════════
Brand name: {brand_name}
Tagline: {tagline}
Mission: {mission}
Brand promise: {promise}
Personality: {', '.join(traits)}
Voice: {', '.join(voice_is)}
Core values: {', '.join(values)}

Origin story (use this verbatim in the brand story section):
{origin}

═══════════════════════════════════
PAGE SECTIONS (build all of these)
═══════════════════════════════════

1. STICKY NAVIGATION
   - Brand name in primary color, bold
   - Links: The Problem | Our Solution | Market | Our Story | Visual Identity | Roadmap | Get Started
   - Translucent/frosted glass effect on scroll
   - Smooth scroll to sections

2. HERO SECTION
   - Tagline: "{tagline}" in accent color at ~24px
   - Brand name "{brand_name}" at display scale (80-120px) in primary or white
   - Promise: "{promise}"
   - Large CTA button in accent color — copy: "{tagline_gtm or 'Get Started'}"
   - Full-width with gradient background using primary + secondary colors

3. THE PROBLEM SECTION
   - Headline: something compelling about the market pain
   - 3 pain point cards based on these real competitor weaknesses:"""

    for pp in pain_points[:3]:
        prompt += f"\n   * [{pp.theme}]: {pp.description}"

    prompt += f"""

4. OUR SOLUTION SECTION
   - Competitive advantage: {advantage}
   - 3-4 feature cards with icons
   - Value hooks (use these verbatim):"""

    for h in hooks[:3]:
        prompt += f"\n   * {h}"

    prompt += f"""

5. MARKET POSITION SECTION (INTERACTIVE CHART)
   Build an interactive scatter plot using Recharts:
   - X-axis: "{axis_x}" ({axis_x_low} → {axis_x_high})
   - Y-axis: "{axis_y}" ({axis_y_low} → {axis_y_high})
   - Competitor dots (blue): {', '.join(comp_data)}
   - {brand_name} position (accent color, star shape, larger): top-right white space
   - Custom tooltips showing competitor name on hover
   - Animate on scroll into view
   - Dark background styled with brand colors

6. BRAND STORY SECTION
   - Use the origin story text above
   - Large pull quote with accent color
   - Split layout: story text | founder visual placeholder

7. VISUAL IDENTITY SECTION
   - Color swatches: large premium boxes for each color with name and hex
   - Typography specimens: show both fonts at large scale with sample text
   - Logo placeholder areas (3 boxes labeled "Logo Concept 1", "Logo Concept 2", "Logo Concept 3")

8. GO-TO-MARKET ROADMAP
   - 3-phase timeline or card layout:"""

    for i, phase in enumerate(phases[:3]):
        prompt += f"\n   Phase {i+1}: {phase.phase_name} — {phase.strategic_objective}"

    if channels:
        prompt += "\n   - Primary channels:"
        for ch in channels:
            prompt += f"\n     * {ch.channel_name} ({ch.allocation_weight})"

    prompt += f"""

9. EMAIL/WAITLIST CTA SECTION
   - Full-width section with primary color background
   - Headline in brand voice
   - CTA button copy specific to this brand — NOT "Subscribe"
   - Email input field styled to match brand
   - Supporting copy: "{tagline}"

═══════════════════════════════════
ANIMATION REQUIREMENTS
═══════════════════════════════════
- Use Framer Motion's useInView to trigger animations
- Elements: opacity 0 → 1, y: 30 → 0, transition: 0.7s ease
- Stagger children with 0.1s delay
- Chart animates on scroll into view
- All hover states: 0.25s ease transition
- Smooth scroll behavior on entire page

═══════════════════════════════════
QUALITY STANDARDS
═══════════════════════════════════
NEVER do these:
- Plain white background + black text for entire page
- Default browser card styles (box-shadow: 0 2px 4px rgba(0,0,0,0.1))
- Everything centered and stacked in one column
- Generic marketing copy ("We are passionate about...")
- No animations or transitions
- Color used only on text, never as atmosphere

MUST do these:
- Every section has a distinct layout (not all stacked vertically)
- Typography at real scale (hero headline minimum 80px)
- Sections breathe (120-160px vertical padding)
- The competitive chart is styled with brand colors
- CTA copy is brand-specific

Target audience: {target}
Positioning: {positioning}

Build this as a complete, production-ready React application that would impress both investors and the target customer on first load."""

    return prompt


class LovableAgent:
    """
    Generates a Lovable Build-with-URL link from pipeline data.
    Free tier — no API key required.
    """

    def generate_url(
        self,
        brand_name: str,
        identity,
        analysis,
        strategy,
        naming,
        visual,
    ) -> str:
        """Build and return the full Lovable URL."""
        logger.info(f"Lovable Agent: building URL for '{brand_name}'.")

        prompt = _build_lovable_prompt(
            brand_name=brand_name,
            identity=identity,
            analysis=analysis,
            strategy=strategy,
            naming=naming,
            visual=visual,
        )

        logger.info(f"Lovable prompt length: {len(prompt)} characters.")

        # URL-encode the prompt
        encoded = urllib.parse.quote(prompt, safe='')
        url = f"https://lovable.dev/?autosubmit=true#prompt={encoded}"

        logger.info(f"Lovable URL generated ({len(url)} chars).")
        return url

    def open_in_browser(self, url: str) -> None:
        """Open the Lovable URL in the default browser."""
        try:
            webbrowser.open(url)
            logger.info("Lovable URL opened in browser.")
        except Exception as e:
            logger.warning(f"Could not open browser: {e}")

    def save_url(self, url: str, brand_name: str, output_dir: Path = None) -> Path:
        """Save the Lovable URL to a file for later use."""
        if output_dir is None:
            output_dir = Path("brand_packs") / brand_name.lower().replace(" ", "_")
        output_dir.mkdir(parents=True, exist_ok=True)

        url_file = output_dir / "lovable_url.txt"
        url_file.write_text(url)
        logger.info(f"Lovable URL saved to {url_file}")
        return url_file


    def save_claude_code_prompt(
        self,
        brand_name: str,
        identity,
        analysis,
        strategy,
        naming,
        visual,
        output_dir: Path = None,
    ) -> Path:
        """
        Save a ready-to-paste Claude Code prompt to brand_packs/[brand]/claude_code_prompt.txt.
        User opens Claude Code, pastes this, and gets a live Lovable URL back automatically.
        """
        if output_dir is None:
            output_dir = Path("brand_packs") / brand_name.lower().replace(" ", "_")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build the same detailed prompt used for Build with URL
        brief = _build_lovable_prompt(
            brand_name=brand_name,
            identity=identity,
            analysis=analysis,
            strategy=strategy,
            naming=naming,
            visual=visual,
        )

        prompt = f"""Use the Lovable MCP server to build and deploy a live app for {brand_name}.

Follow these exact steps in order:

1. Use workspace_id: "mdl9M01eYDCjxKTRTY9o"
2. Call create_project with:
   - workspace_id: (from step 1)
   - description: "{brand_name} brand experience"
   - initial_message: (the full brand brief below)

3. Wait for the build to complete (poll with get_project until status is ready)

4. Call deploy_project with the project_id from step 2

5. Return the live URL to me

---
FULL BRAND BRIEF FOR initial_message:
---

{brief}
"""

        prompt_file = output_dir / "claude_code_prompt.txt"
        prompt_file.write_text(prompt)
        logger.info(f"Claude Code prompt saved to {prompt_file}")
        return prompt_file