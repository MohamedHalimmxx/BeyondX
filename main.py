from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading (shared by both modes)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # env vars may be set directly in the shell


# ---------------------------------------------------------------------------
# ANSI colour helpers (graceful fallback on Windows without colorama)
# ---------------------------------------------------------------------------

def _supports_colour() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


RESET  = "\033[0m"  if _supports_colour() else ""
BOLD   = "\033[1m"  if _supports_colour() else ""
GREEN  = "\033[32m" if _supports_colour() else ""
YELLOW = "\033[33m" if _supports_colour() else ""
CYAN   = "\033[36m" if _supports_colour() else ""
RED    = "\033[31m" if _supports_colour() else ""
DIM    = "\033[2m"  if _supports_colour() else ""


def _banner(text: str) -> str:
    bar = "═" * 62
    return f"\n{BOLD}{CYAN}{bar}\n  {text}\n{bar}{RESET}"


# ---------------------------------------------------------------------------
# Mode selector
# ---------------------------------------------------------------------------

def _select_mode() -> int:
    """
    Prints the main menu and returns the user's choice (1 or 2).
    Loops until a valid choice is entered.
    """
    print(_banner("AgenticApp — Choose a Mode"))
    print(f"""
  {BOLD}[1]{RESET}  {CYAN}BrandGenius{RESET}
       Market research · Competitor analysis · Brand naming
       Brand identity · Visual identity · UI generation

  {BOLD}[2]{RESET}  {CYAN}Content Creator Agent{RESET}
       Social media strategy · Content calendar
       Post generation · Campaign ideas · Chat follow-up
    """)

    while True:
        sys.stdout.write(f"  {BOLD}Enter 1 or 2:{RESET}  ")
        sys.stdout.flush()
        choice = input().strip()
        if choice in ("1", "2"):
            return int(choice)
        print(f"  {YELLOW}⚠{RESET}  Please enter 1 or 2.")


# ===========================================================================
# MODE 1 — BrandGenius
# ===========================================================================

def _run_brandgenius() -> None:
    """
    Imports and runs the original BrandGenius multi-agent pipeline.
    All imports are deferred so that missing deps for mode 2 don't
    break mode 1, and vice-versa.
    """
    # ── Deferred imports ──────────────────────────────────────────────────
    from config.settings import settings
    from agents.research_agent import AutonomousResearchAgent
    from agents.analyst_agent import BrandAnalystAgent
    from agents.strategy_agent import StrategyWriterAgent
    from agents.naming_agent import BrandNamingAgent
    from agents.brand_identity_agent import BrandIdentityAgent
    from state.brand_identity_state import BrandIdentityOutput
    from utils.input_validator import validate_brand_brief, BrandBriefValidationError
    from nodes.naming_node import naming_node
    from nodes.analyst_node import generate_positioning_statement
    from utils.brand_brief import collect_brand_brief
    from utils.positioning_map import render_positioning_map
    from config.llm_factory import get_primary_llm
    from agents.visual_identity_agent import VisualIdentityAgent

    # ── Logging ───────────────────────────────────────────────────────────
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("research_agent.main")

    # ── Async pipeline ────────────────────────────────────────────────────
    async def _pipeline() -> None:
        print("=" * 70)
        print("BRANDGENIUS — MARKET RESEARCH + BRAND ANALYSIS + GO-TO-MARKET")
        print("=" * 70)

        try:
            user_idea = input("\nEnter your startup or business idea description:\n> ").strip()
            if not user_idea:
                print("Error: Business idea cannot be empty.")
                return

            # Brand Brief — location asked FIRST so research uses correct city
            brand_brief = collect_brand_brief(user_idea)

            try:
                validate_brand_brief(
                    idea=user_idea,
                    location=brand_brief.location,
                    differentiator=brand_brief.differentiator,
                    ideal_customer=brand_brief.ideal_customer,
                    non_negotiable=brand_brief.non_negotiable,
                )
            except BrandBriefValidationError as e:
                print(f"\n{e}\n")
                return

            # Build location-enriched idea for research
            location_context = f" in {brand_brief.location}" if brand_brief.location != "Not specified" else ""
            research_idea = f"{user_idea}{location_context}"

            # ── Stage 1 — Market Research ─────────────────────────────────
            print("\n[Stage 1] Running market research...")
            print("(This may take a minute. Please hold.)\n")
            research_agent = AutonomousResearchAgent()
            research_result = await research_agent.execute_research(idea=research_idea)

            final_report   = research_result.get("report", research_result.get("final_report", ""))
            gathered_data  = research_result.get("gathered_data", [])
            insights       = research_result.get("insights", [])

            print("\n" + "=" * 70)
            print("MARKET RESEARCH REPORT")
            print("=" * 70)
            print(final_report)

            # Build full enriched idea for analyst + strategy
            enriched_idea = (
                f"{user_idea}{location_context}\n"
                f"Client differentiator: {brand_brief.differentiator}\n"
                f"Ideal customer: {brand_brief.ideal_customer}\n"
                f"Non-negotiable: {brand_brief.non_negotiable}"
            )

            # ── Stage 2 — Brand Analysis ──────────────────────────────────
            print("\n[Stage 2] Running full brand positioning analysis...")
            print("(Enriching competitors with real reviews and web data. Please hold.)\n")

            analyst = BrandAnalystAgent()
            research_report = final_report if final_report else "\n".join(gathered_data)
            if len(research_report) > 8000:
                research_report = research_report[:8000] + "\n[... truncated ...]"
            analysis = await analyst.execute_analysis(
                idea=enriched_idea,
                research_report=research_report,
                insights=insights[:20],
            )

            print("\n" + "=" * 70)
            print("BRAND POSITIONING ANALYSIS")
            print("=" * 70)

            positioning_map_string = render_positioning_map(analysis)
            print("\n## Competitive Positioning Map")
            print(positioning_map_string)

            print(f"\n## Positioning Axes")
            print(f"  Axis 1: {analysis.positioning_axes.axis_1_label} "
                  f"({analysis.positioning_axes.axis_1_low} → {analysis.positioning_axes.axis_1_high})")
            print(f"  Axis 2: {analysis.positioning_axes.axis_2_label} "
                  f"({analysis.positioning_axes.axis_2_low} → {analysis.positioning_axes.axis_2_high})")
            print(f"  Why: {analysis.positioning_axes.reasoning}")

            print(f"\n## Competitor Profiles ({len(analysis.competitors)} enriched)")
            for c in analysis.competitors:
                rating_str = f"{c.rating}/5 ({c.review_count} reviews)" if c.rating is not None else "No rating data"
                print(f"\n  {c.name} — {rating_str} [{c.data_confidence} confidence]")
                print(f"    {analysis.positioning_axes.axis_1_label}: {c.axis_1_score}/10 ({c.pricing_tier})")
                print(f"    {analysis.positioning_axes.axis_2_label}: {c.axis_2_score}/10 ({c.service_style})")
                print(f"    Personality: {c.brand_personality}")
                print(f"    Audience: {c.target_audience}")
                print(f"    Strengths: {', '.join(c.top_strengths)}")
                print(f"    Weaknesses: {', '.join(c.top_weaknesses)}")

            print(f"\n## White Spaces ({len(analysis.white_spaces)} identified)")
            for i, ws in enumerate(analysis.white_spaces, 1):
                print(f"\n  [{i}] {ws.description}")
                print(f"      Position: {ws.axis_1_position} × {ws.axis_2_position}")
                print(f"      Why it exists: {ws.why_it_exists}")
                print(f"      Evidence: {ws.evidence}")

            print(f"\n## Customer Pain Points ({len(analysis.pain_points)} identified)")
            for p in analysis.pain_points:
                print(f"\n  [{p.theme}]")
                print(f"  Seen in: {', '.join(p.affected_competitors)}")
                print(f"  Problem: {p.description}")
                print(f"  Evidence: {p.evidence}")
                print(f"  Opportunity: {p.opportunity}")

            print(f"\n## Positioning Recommendation")
            print(f"  {analysis.positioning_recommendation}")

            print(f"\n## Target Audience")
            print(f"  {analysis.target_audience_summary}")

            print(f"\n## Competitive Advantage")
            print(f"  {analysis.competitive_advantage}")

            print("\n[Generating positioning statement...]\n")
            llm = get_primary_llm()
            statement = await generate_positioning_statement(
                idea=enriched_idea,
                analysis=analysis,
                llm=llm,
            )

            print("\n" + "=" * 70)
            print("BRAND POSITIONING STATEMENT")
            print("=" * 70)
            print(f"\n  {statement.full_statement}")
            print(f"\n  For:      {statement.for_audience}")
            print(f"  Who:      {statement.who_need}")
            print(f"  Is the:   {statement.is_the}")
            print(f"  That:     {statement.that}")
            print(f"  Unlike:   {statement.unlike}")
            print(f"  We:       {statement.we}")

            # ── Stage 3 — Strategy Writer ─────────────────────────────────
            print("\n" + "=" * 70)
            print("[Stage 3] Compiling custom Go-To-Market strategy playbook...")
            print("(Translating competitor intelligence into dynamic copy hooks. Please hold.)\n")

            strategist = StrategyWriterAgent()
            strategy_playbook, strategy_plan = await strategist.generate_plan({
                "idea": enriched_idea,
                "research_report": final_report,
                "positioning_statement": statement.full_statement,
                "positioning_map_ascii": positioning_map_string,
            })

            print("\n" + "=" * 70)
            print("STRATEGIC GO-TO-MARKET PLAYBOOK GENERATED")
            print("=" * 70)
            print(strategy_playbook)

            print("\n" + "=" * 70)
            print("Operation completed successfully.")

            # ── Stage 4 — Brand Naming ────────────────────────────────────
            print("\n" + "=" * 70)
            print("[Stage 4] Generating brand name candidates...")
            print("(Checking domain availability. Please hold.)\n")

            naming_agent = BrandNamingAgent()
            naming_output = await naming_agent.generate_names(
                idea=enriched_idea,
                positioning_statement=statement.full_statement,
                analysis=analysis,
                brand_brief=brand_brief,
            )

            print("\n" + "=" * 70)
            print("BRAND NAMING REPORT")
            print("=" * 70)
            print(f"\n  Naming Strategy: {naming_output.naming_strategy}")
            print(f"\n  Names to Avoid: {', '.join(naming_output.names_to_avoid)}")

            print(f"\n## Brand Name Candidates ({len(naming_output.candidates)} generated)")
            print(f"  {'#':<3} {'Name':<15} {'Score':<7} {'.com':<10} {'.io':<10} {'Conflict':<12}")
            print(f"  {'-'*3} {'-'*15} {'-'*7} {'-'*10} {'-'*10} {'-'*12}")

            for i, c in enumerate(naming_output.candidates, 1):
                com      = "✅ free" if c.domain_com == "available" else "❌ taken" if c.domain_com == "taken" else "?"
                io       = "✅ free" if c.domain_io == "available" else "❌ taken" if c.domain_io == "taken" else "?"
                conflict = "⚠️ conflict" if c.brand_conflict == "conflict" else "✅ clear" if c.brand_conflict == "clear" else "?"
                print(f"  {i:<3} {c.name:<15} {c.score:<7.1f} {com:<10} {io:<10} {conflict:<12}")
                if c.brand_conflict == "conflict" and c.conflict_reason:
                    print(f"       ↳ {c.conflict_reason}")

            print(f"\n## Top Recommendation")
            print(f"  {naming_output.top_recommendation}")

            print(f"\n## Name Details")
            for i, c in enumerate(naming_output.candidates[:3], 1):
                print(f"\n  [{i}] {c.name} — {c.pronunciation_guide}")
                print(f"      Meaning: {c.meaning_and_origin}")
                print(f"      Why it fits: {c.positioning_fit}")

            print("\n" + "=" * 70)
            print("Operation completed successfully.")

            # ── Stage 5 — Brand Identity ──────────────────────────────────
            print("\n" + "=" * 70)
            print("[Stage 5] Building brand identity document...")
            print("(Mission, vision, origin story, voice, values, tagline. Please hold.)\n")

            identity_agent = BrandIdentityAgent()
            identity = await identity_agent.generate_identity(
                idea=enriched_idea,
                positioning_statement=statement.full_statement,
                naming_output=naming_output,
                analysis=analysis,
                brand_brief=brand_brief,
            )

            print("\n" + "=" * 70)
            print("BRAND IDENTITY DOCUMENT")
            print("=" * 70)

            print(f"\n## Selected Brand Name")
            print(f"  {identity.selected_name}")
            print(f"  Rationale: {identity.name_rationale}")

            print(f"\n## Mission")
            print(f"  {identity.mission}")

            print(f"\n## Vision")
            print(f"  {identity.vision}")

            print(f"\n## Brand Promise")
            print(f"  {identity.brand_promise}")

            print(f"\n## Origin Story")
            for para in identity.origin_story.split("\n\n"):
                if para.strip():
                    print(f"\n  {para.strip()}")

            print(f"\n## Personality Traits")
            for trait in identity.personality_traits:
                print(f"  — {trait}")

            print(f"\n## Brand Voice")
            print(f"  IS:")
            for v in identity.brand_voice_is:
                print(f"    + {v}")
            print(f"  NEVER:")
            for v in identity.brand_voice_never:
                print(f"    - {v}")

            print(f"\n## Core Values")
            for val in identity.core_values:
                print(f"  • {val}")

            print(f"\n## Tagline")
            print(f"  \"{identity.tagline}\"")

            print("\n" + "=" * 70)
            print("Operation completed successfully.")

            # ── Stage 6 — Visual Identity ─────────────────────────────────
            visual = None
            try:
                print("\n" + "=" * 70)
                print("[Stage 6] Generating visual identity...")
                print("(Color palette, typography, and logo concepts. Please hold.)\n")

                visual_agent   = VisualIdentityAgent()
                brand_pack_dir = Path("brand_packs") / identity.selected_name.lower().replace(" ", "_")

                visual = await visual_agent.generate_visual_identity(
                    brand_name=identity.selected_name,
                    identity=identity,
                    analysis=analysis,
                    output_dir=brand_pack_dir,
                )

                print("\n" + "=" * 70)
                print("VISUAL IDENTITY")
                print("=" * 70)

                print(f"\n## Visual Direction")
                print(f"  {visual.visual_direction}")

                print(f"\n## Color Palette")
                for c in visual.colors:
                    print(f"\n  [{c.role.upper()}] {c.name} — {c.hex}")
                    print(f"    Rationale: {c.rationale}")
                    print(f"    Usage: {c.usage}")

                print(f"\n## Typography")
                print(f"\n  Primary: {visual.typography.primary_font}")
                print(f"    Role: {visual.typography.primary_font_role}")
                print(f"    URL: {visual.typography.primary_font_url}")
                print(f"\n  Secondary: {visual.typography.secondary_font}")
                print(f"    Role: {visual.typography.secondary_font_role}")
                print(f"    URL: {visual.typography.secondary_font_url}")
                print(f"\n  Pairing: {visual.typography.pairing_rationale}")

                print(f"\n## Logo Concepts")
                if visual.logo_paths:
                    print(f"  {len(visual.logo_paths)} logo concepts generated:")
                    for path in visual.logo_paths:
                        print(f"    → {path}")
                else:
                    print("  Logo generation unavailable — visual brief saved.")

                print(f"\n## Brand Pack Location")
                print(f"  {brand_pack_dir}/")

                print("\n" + "=" * 70)
                print("Operation completed successfully.")

            except Exception as e:
                print(f"\n  ⚠️  Visual identity generation failed: {str(e)[:80]}")
                print("  Stages 1-5 completed successfully. Fix Gemini key and rerun.")
                visual = None

            # ── Stage 7 — Brand Experience ────────────────────────────────
            print("\n" + "=" * 70)
            print("[Stage 7] Generating brand experience...")
            print("(Building your premium HTML brand experience. Please hold.)\n")

            if visual is None:
                print("  ⚠️  Skipping Stage 7 — visual identity (Stage 6) did not complete.")
                print("  Fix the Gemini key and rerun to generate the brand experience.")
            else:
                try:
                    from agents.brand_book_agent import BrandBookAgent
                    brand_book_agent = BrandBookAgent()
                    brand_safe       = identity.selected_name.lower().replace(" ", "_")
                    brand_book_path  = await brand_book_agent.generate(
                        brand_name=identity.selected_name,
                        identity=identity,
                        analysis=analysis,
                        strategy=strategy_plan,
                        naming=naming_output,
                        visual=visual,
                        output_dir=Path("brand_packs") / brand_safe,
                    )
                    print(f"\n  ✅ Brand experience saved: {brand_book_path}")
                    print(f"     Open in browser: file:///Users/hanatarek/BeyondX/{brand_book_path}")
                except Exception as e:
                    print(f"\n  ⚠️  Brand experience generation failed: {str(e)[:100]}")

            # ── Stage 8 — Lovable ─────────────────────────────────────────
            print("\n" + "=" * 70)
            print("[Stage 8] Generating Lovable app files...")
            print("(Build with URL + Claude Code prompt ready.)\n")

            try:
                from agents.lovable_agent import LovableAgent
                lovable    = LovableAgent()
                brand_safe = identity.selected_name.lower().replace(" ", "_")
                out_dir    = Path("brand_packs") / brand_safe

                lovable_url = lovable.generate_url(
                    brand_name=identity.selected_name,
                    identity=identity,
                    analysis=analysis,
                    strategy=strategy_plan,
                    naming=naming_output,
                    visual=visual,
                )
                lovable.save_url(lovable_url, identity.selected_name, out_dir)

                prompt_file = lovable.save_claude_code_prompt(
                    brand_name=identity.selected_name,
                    identity=identity,
                    analysis=analysis,
                    strategy=strategy_plan,
                    naming=naming_output,
                    visual=visual,
                    output_dir=out_dir,
                )

                print(f"  ✅ Build with URL saved: {out_dir}/lovable_url.txt")
                print(f"  ✅ Claude Code prompt saved: {prompt_file}")
                print(f"\n  To build live React app:")
                print(f"  Option A — click the URL in lovable_url.txt (~1-2 credits)")
                print(f"  Option B — open Claude Code, paste {prompt_file}")

            except Exception as e:
                print(f"\n  ⚠️  Stage 8 failed: {str(e)[:80]}")

        except KeyboardInterrupt:
            print("\n\nCancelled by user.")
        except Exception as err:
            print(f"\nPipeline error: {str(err)}")
            logger.error("Runtime error.", exc_info=True)

    asyncio.run(_pipeline())


# ===========================================================================
# MODE 2 — Content Creator Agent
# ===========================================================================

def _run_content_creator(quiet: bool = False, save_output: bool = False) -> int:
    """
    Imports and runs the Content Creator Agent from the
    content_gen_agent sub-folder.
    Returns the exit code (0 = success/partial, 1 = failed/error).
    """
    # ── Add content_gen_agent folder to sys.path so its modules resolve ──
    content_agent_dir = Path(__file__).parent / "content_gen_agent"
    if str(content_agent_dir) not in sys.path:
        sys.path.insert(0, str(content_agent_dir))

    # ── Deferred imports from content_gen_agent ───────────────────────────
    from content_gen_agent.content_creator_agent import ContentCreatorAgent, ContentCreatorOutput
    from content_gen_agent.session_memory import get_session_memory
    from content_gen_agent.chat_loop import run_chat_loop

    import json
    import uuid
    from datetime import datetime, timezone
    from typing import Any

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("content_creator.main")

    # ── Colour helpers (already defined at module level) ──────────────────

    def _h1(text: str) -> str:
        bar = "═" * 60
        return f"\n{BOLD}{CYAN}{bar}\n  {text}\n{bar}{RESET}"

    def _h2(text: str) -> str:
        return f"\n{BOLD}{YELLOW}── {text} {'─' * max(0, 55 - len(text))}{RESET}"

    def _ok(text: str) -> str:
        return f"{GREEN}✓{RESET} {text}"

    def _warn(text: str) -> str:
        return f"{YELLOW}⚠{RESET} {text}"

    def _err(text: str) -> str:
        return f"{RED}✗{RESET} {text}"

    def _dim(text: str) -> str:
        return f"{DIM}{text}{RESET}"

    def _wrap(text: str, width: int = 80, indent: int = 4) -> str:
        prefix = " " * indent
        return textwrap.fill(text, width=width, initial_indent=prefix, subsequent_indent=prefix)

    # ── Valid platforms ───────────────────────────────────────────────────
    VALID_PLATFORMS: list[str] = [
        "Instagram", "TikTok", "LinkedIn", "X",
        "Facebook", "YouTube Shorts", "Pinterest", "Threads",
    ]

    # ── Interactive input helpers ─────────────────────────────────────────
    def _prompt(label: str, example: str = "", required: bool = True) -> str:
        hint = f"  {_dim('e.g. ' + example)}" if example else ""
        while True:
            sys.stdout.write(f"\n  {BOLD}{label}{RESET}{hint}\n  → ")
            sys.stdout.flush()
            value = input().strip()
            if value:
                return value
            if not required:
                return ""
            print(f"  {_warn('This field is required. Please enter a value.')}")

    def _collect_brand_input() -> dict[str, Any]:
        print(_h1("BRAND SETUP — Enter Your Brand Details"))
        print(f"  {_dim('Fill in each field and press Enter to continue.')}")
        print(f"  {_dim('Press Ctrl+C at any time to cancel.')}\n")

        brand_name = _prompt("Brand Name", example="Sehaty / Bloom Coffee / TechCorp")
        industry   = _prompt("Industry", example="Healthcare Technology / Specialty Coffee / Fashion")
        country    = _prompt("Country", example="Egypt / UAE / Saudi Arabia")
        city       = _prompt("City", example="Cairo / Dubai / Riyadh")

        while True:
            foundation_date = _prompt("Foundation Date (YYYY-MM-DD)", example="2019-03-15 / 2022-06-01")
            try:
                datetime.strptime(foundation_date, "%Y-%m-%d")
                break
            except ValueError:
                print(f"  {_err('Invalid format. Use YYYY-MM-DD (e.g. 2022-06-01).')}")

        print(f"\n  {BOLD}Social Platforms{RESET}")
        print(f"  {_dim('Available options:')}")
        for i, p in enumerate(VALID_PLATFORMS, 1):
            print(f"    {_dim(str(i) + '.')} {p}")
        print(f"  {_dim('Enter numbers separated by commas  →  e.g. 1,2')}")
        print(f"  {_dim('Or type names directly             →  e.g. Instagram,TikTok')}")

        while True:
            sys.stdout.write("\n  → ")
            sys.stdout.flush()
            raw = input().strip()
            if not raw:
                print(f"  {_warn('Please select at least one platform.')}")
                continue

            parts     = [p.strip() for p in raw.split(",") if p.strip()]
            platforms: list[str] = []

            if all(p.isdigit() for p in parts):
                valid = True
                for part in parts:
                    idx = int(part) - 1
                    if 0 <= idx < len(VALID_PLATFORMS):
                        name = VALID_PLATFORMS[idx]
                        if name not in platforms:
                            platforms.append(name)
                    else:
                        print(f"  {_err(f'Invalid number: {part}. Choose 1–{len(VALID_PLATFORMS)}.')}")
                        valid = False
                        break
                if not valid:
                    continue
            else:
                invalid: list[str] = []
                for part in parts:
                    match = next((v for v in VALID_PLATFORMS if v.lower() == part.lower()), None)
                    if match:
                        if match not in platforms:
                            platforms.append(match)
                    else:
                        invalid.append(part)
                if invalid:
                    print(f"  {_err(f'Unknown platform(s): {invalid}')}")
                    print(f"  {_dim('Valid: ' + ', '.join(VALID_PLATFORMS))}")
                    continue

            if platforms:
                print(f"  {_ok('Selected: ' + ', '.join(platforms))}")
                break

        while True:
            raw_posts = _prompt("Posts Per Month (1–120)", example="10 / 20 / 30")
            try:
                posts_per_month = int(raw_posts)
                if 1 <= posts_per_month <= 120:
                    break
                print(f"  {_err('Please enter a number between 1 and 120.')}")
            except ValueError:
                print(f"  {_err('Please enter a valid integer (e.g. 20).')}")

        config = {
            "brand_name":       brand_name,
            "industry":         industry,
            "country":          country,
            "city":             city,
            "foundation_date":  foundation_date,
            "social_platforms": platforms,
            "posts_per_month":  posts_per_month,
        }

        print(_h2("CONFIRM YOUR BRAND DETAILS"))
        print(f"  Brand     : {BOLD}{config['brand_name']}{RESET}")
        print(f"  Industry  : {config['industry']}")
        print(f"  Location  : {config['city']}, {config['country']}")
        print(f"  Founded   : {config['foundation_date']}")
        print(f"  Platforms : {', '.join(config['social_platforms'])}")
        print(f"  Posts/Month: {config['posts_per_month']}")

        while True:
            print(f"\n  {BOLD}Proceed?{RESET} {_dim('(yes / no / edit)')}")
            sys.stdout.write("  → ")
            sys.stdout.flush()
            answer = input().strip().lower()
            if answer in ("yes", "y", ""):
                print(_ok("Confirmed. Starting agent...\n"))
                return config
            elif answer in ("no", "n"):
                print(_warn("Run cancelled."))
                sys.exit(0)
            elif answer in ("edit", "e"):
                return _collect_brand_input()
            else:
                print(f"  {_dim('Type yes, no, or edit.')}")

    # ── Environment check ─────────────────────────────────────────────────
    def _check_environment() -> list[str]:
        required = ["GROQ_API_KEY", "TAVILY_API_KEY"]
        return [var for var in required if not os.getenv(var)]

    # ── Output saver ──────────────────────────────────────────────────────
    def _save_output(output: ContentCreatorOutput, config: dict[str, Any]) -> Path:
        outputs_dir = Path("outputs")
        outputs_dir.mkdir(exist_ok=True)
        timestamp  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        brand_slug = config["brand_name"].lower().replace(" ", "_")
        filename   = f"{brand_slug}_{timestamp}_{output.run_id[:8]}.json"
        filepath   = outputs_dir / filename
        output_dict = output.model_dump()
        output_dict["_run_config"] = config
        output_dict["_saved_at"]   = datetime.now(timezone.utc).isoformat()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, ensure_ascii=False, indent=2, default=str)
        return filepath

    # ── Output printer (inline class) ────────────────────────────────────
    class OutputPrinter:
        def __init__(self, quiet: bool = False) -> None:
            self.quiet = quiet

        def print_all(self, output: ContentCreatorOutput, config: dict[str, Any]) -> None:
            self._print_header(output, config)
            self._print_summary(output)
            if not self.quiet:
                self._print_brand_profile(output)
                self._print_strategy(output)
                self._print_pillars(output)
                self._print_calendar_overview(output)
                self._print_sample_posts(output, sample_count=3)
                self._print_hashtag_bank(output)
                self._print_cta_bank(output)
                self._print_campaigns(output)
                self._print_anniversary(output)
            self._print_execution_log(output)
            self._print_errors(output)
            self._print_footer(output)

        def _print_header(self, output, config):
            print(_h1("CONTENT CREATOR AGENT — RUN REPORT"))
            print(f"  Run ID    : {BOLD}{output.run_id}{RESET}")
            print(f"  Brand     : {BOLD}{config['brand_name']}{RESET}")
            print(f"  Industry  : {config['industry']}")
            print(f"  Location  : {config['city']}, {config['country']}")
            print(f"  Platforms : {', '.join(config['social_platforms'])}")
            print(f"  Posts     : {config['posts_per_month']} requested")
            print(f"  Timestamp : {output.generation_timestamp}")

        def _print_summary(self, output):
            print(_h2("RUN SUMMARY"))
            s = output.summary
            status_colour = {"success": GREEN, "partial": YELLOW, "failed": RED}.get(output.status, RESET)
            print(f"  Status          : {BOLD}{status_colour}{output.status.upper()}{RESET}")
            print(f"  Posts           : {s.get('posts_generated', 0)} / {s.get('posts_requested', 0)} generated")
            print(f"  Campaigns       : {s.get('campaigns_generated', 0)}")
            print(f"  Anniversary     : {'YES' if s.get('has_anniversary_campaign') else 'NO'}")
            print(f"  Evidence Sources: {s.get('evidence_sources_used', 0)}")
            print(f"  Nodes           : {s.get('nodes_succeeded', 0)} succeeded | {s.get('nodes_partial', 0)} partial | {s.get('nodes_failed', 0)} failed")
            print(f"  Errors          : {s.get('error_count', 0)}")
            print(f"  Total Duration  : {s.get('total_duration_ms', 0):,} ms ({s.get('total_duration_ms', 0) / 1000:.1f}s)")
            print(f"  Model           : {s.get('model_used', 'N/A')}")

        def _print_brand_profile(self, output):
            print(_h2("BRAND PROFILE"))
            profile = output.brand_profile
            if not profile:
                print(_warn("  Brand profile not available."))
                return
            fields = [("Summary","summary"),("Brand Age","brand_age_years"),("Target Audience","target_audience"),
                      ("Brand Tone","brand_tone"),("Value Prop","unique_value_prop"),("Language","content_language"),
                      ("Market Position","market_positioning"),("Cultural Context","cultural_context")]
            for label, key in fields:
                value = profile.get(key, "N/A")
                if isinstance(value, str) and len(value) > 80:
                    print(f"  {label}:")
                    print(_wrap(value))
                else:
                    print(f"  {label:<18}: {value}")
            pain_points = profile.get("audience_pain_points", [])
            if pain_points:
                print("  Pain Points:")
                for pt in pain_points:
                    print(f"    • {pt}")
            evidence = profile.get("evidence_used", [])
            if evidence:
                print(f"  Evidence Used   : {len(evidence)} source(s)")
                for e in evidence[:3]:
                    print(_dim(f"    - {e}"))

        def _print_strategy(self, output):
            print(_h2("CONTENT STRATEGY"))
            strategy = output.content_strategy
            if not strategy:
                print(_warn("  Strategy not available."))
                return
            print("  Strategic Goal:")
            print(_wrap(strategy.get("strategic_goal", "N/A")))
            print("  Audience Insight:")
            print(_wrap(strategy.get("audience_insight", "N/A")))
            print(f"  Confidence      : {strategy.get('strategy_metadata', {}).get('strategy_confidence', 'N/A')}")
            content_mix = strategy.get("content_mix", {})
            if content_mix:
                print("  Content Mix:")
                for k in ["educational","entertaining","promotional","community","behind_the_scenes"]:
                    val = content_mix.get(k, 0)
                    if isinstance(val, (int, float)):
                        print(f"    {k:<22}: {val:>3}% {'█' * (val // 5)}")
            platform_strategy = strategy.get("platform_strategy", {})
            if platform_strategy:
                print("  Platform Strategy:")
                for platform, details in platform_strategy.items():
                    print(f"    {platform:<16}: {details.get('role', 'N/A')}")
                    print(_dim(f"      Frequency: {details.get('posting_frequency', 'N/A')}"))

        def _print_pillars(self, output):
            print(_h2("CONTENT PILLARS"))
            if not output.content_pillars:
                print(_warn("  No pillars available."))
                return
            for pillar in output.content_pillars:
                pct  = pillar.get("percentage", 0)
                print(f"\n  {BOLD}{pillar.get('name', 'Unknown')}{RESET} — {pct}% {'█' * (pct // 5)}")
                if pillar.get("description"):
                    print(_wrap(pillar["description"], indent=4))
                if pillar.get("post_types"):
                    print(f"    Formats: {', '.join(pillar['post_types'])}")

        def _print_calendar_overview(self, output):
            print(_h2("CALENDAR OVERVIEW"))
            posts = output.generated_posts or output.content_calendar
            if not posts:
                print(_warn("  No calendar available."))
                return
            by_platform: dict[str, list] = {}
            by_week: dict[int, int] = {}
            by_pillar: dict[str, int] = {}
            for post in posts:
                by_platform.setdefault(post.get("platform", "Unknown"), []).append(post)
                w = post.get("week", 0)
                by_week[w] = by_week.get(w, 0) + 1
                p = post.get("content_pillar", "Unknown")
                by_pillar[p] = by_pillar.get(p, 0) + 1
            print(f"  Total Posts     : {len(posts)}")
            print("\n  By Platform:")
            for plat, pp in sorted(by_platform.items()):
                print(f"    {plat:<18}: {len(pp)} posts")
            print("\n  By Week:")
            for week in sorted(by_week.keys()):
                print(f"    Week {week}            : {by_week[week]:>3} posts  {'▪' * by_week[week]}")
            print("\n  By Pillar:")
            for pillar, count in sorted(by_pillar.items()):
                print(f"    {pillar:<28}: {count} posts")

        def _print_sample_posts(self, output, sample_count=3):
            print(_h2(f"SAMPLE GENERATED POSTS (first {sample_count})"))
            posts = output.generated_posts
            if not posts:
                print(_warn("  No generated posts available."))
                return
            for post in posts[:sample_count]:
                print(f"\n  {BOLD}Post #{post.get('post_number')} | Week {post.get('week')} {post.get('day_of_week')} | {post.get('platform')} | {post.get('content_type')}{RESET}")
                print(f"  Pillar  : {post.get('content_pillar', 'N/A')}")
                print(f"  Topic   : {post.get('topic', 'N/A')}")
                caption = post.get("caption", "")
                if caption:
                    print("  Caption :")
                    preview = caption[:300] + ("…" if len(caption) > 300 else "")
                    for line in preview.split("\n")[:6]:
                        print(f"    {line}")
                if post.get("hashtags"):
                    print(f"  Hashtags: {' '.join(post['hashtags'][:8])}")
                if post.get("cta"):
                    print(f"  CTA     : {post['cta']}")
                script = post.get("reel_script")
                if script:
                    hook     = script.get("hook", "")
                    duration = script.get("total_duration_seconds", "N/A")
                    print(f"  Script  : {BOLD}[{duration}s Reel]{RESET} Hook: \"{hook[:80]}{'…' if len(hook) > 80 else ''}\"")
                    print(_dim(f"    {len(script.get('body', []))} body beats | {script.get('audio_note', 'N/A')}"))
                evidence = post.get("evidence_sources", [])
                if evidence:
                    print(_dim(f"  Evidence: {evidence[0][:80]}"))
                print(_dim("  " + "─" * 55))

        def _print_hashtag_bank(self, output):
            print(_h2("HASHTAG BANK"))
            if not output.hashtag_bank:
                print(_warn("  No hashtag bank available."))
                return
            for platform, pillars in output.hashtag_bank.items():
                print(f"\n  {BOLD}{platform}{RESET}")
                for pillar, tags in pillars.items():
                    overflow = f" +{len(tags)-10} more" if len(tags) > 10 else ""
                    print(f"    {pillar:<28}: {' '.join(tags[:10])}{_dim(overflow)}")

        def _print_cta_bank(self, output):
            print(_h2("CTA BANK"))
            if not output.cta_bank:
                print(_warn("  No CTA bank available."))
                return
            print(f"  {len(output.cta_bank)} unique CTAs generated:\n")
            for i, cta in enumerate(output.cta_bank[:10], start=1):
                print(f"  {_dim(str(i) + '.')} {cta}")
            if len(output.cta_bank) > 10:
                print(_dim(f"  … and {len(output.cta_bank) - 10} more"))

        def _print_campaigns(self, output):
            print(_h2("CAMPAIGN IDEAS"))
            if not output.campaign_ideas:
                print(_warn("  No campaign ideas available."))
                return
            for i, campaign in enumerate(output.campaign_ideas, start=1):
                print(f"\n  {BOLD}[{i}] {campaign.get('name', 'Unnamed')}{RESET}")
                print(f"  Duration  : {campaign.get('duration_days', 'N/A')} days | Platforms: {', '.join(campaign.get('platforms', []))}")
                for field in ["objective","core_message","hook","why_now"]:
                    val = campaign.get(field, "")
                    if val:
                        print(_wrap(f"{field.replace('_',' ').title()}: {val[:200]}", indent=4))
                if campaign.get("hashtag"):
                    print(f"    Hashtag: {BOLD}{campaign['hashtag']}{RESET}")
                kpis = campaign.get("kpis", [])
                if kpis:
                    print("    KPIs:")
                    for kpi in kpis[:3]:
                        print(f"      • {kpi}")
                arc = campaign.get("content_arc", [])
                if arc:
                    print("    Content Arc:")
                    for phase in arc:
                        print(f"      {BOLD}{phase.get('phase', '?')}{RESET} ({phase.get('duration_days', '?')} days)")
                        for concept in phase.get("post_concepts", [])[:2]:
                            print(_dim(f"        - {concept[:80]}"))
                evidence = campaign.get("evidence_sources", [])
                if evidence:
                    print(_dim(f"    Evidence: {evidence[0][:80]}"))

        def _print_anniversary(self, output):
            print(_h2("ANNIVERSARY CAMPAIGN"))
            ann = output.anniversary_campaign
            if not ann:
                print(_dim("  No anniversary campaign (outside campaign window)."))
                return
            print(f"\n  {BOLD}Year {ann.get('year_milestone')} — {ann.get('campaign_name', 'N/A')}{RESET}")
            print(f"  Date      : {ann.get('anniversary_date', 'N/A')}" + (" ⭐ MILESTONE YEAR" if ann.get("year_milestone", 0) % 5 == 0 else ""))
            print(f"  Theme     : {ann.get('theme', 'N/A')}")
            if ann.get("key_message"):
                print(_wrap(f"Key Message: {ann['key_message']}", indent=4))
            pieces = ann.get("content_pieces", [])
            if pieces:
                print("  Content Pieces:")
                for piece in pieces[:4]:
                    print(f"    • {piece[:100]}")
            if ann.get("hashtag"):
                print(f"  Hashtag   : {BOLD}{ann['hashtag']}{RESET}")
            if ann.get("community_activation"):
                print(_wrap(f"Community: {ann['community_activation'][:150]}", indent=4))

        def _print_execution_log(self, output):
            print(_h2("NODE EXECUTION LOG"))
            if not output.node_execution_log:
                print(_dim("  No execution log available."))
                return
            for entry in output.node_execution_log:
                status    = entry.get("status", "?")
                icon      = {"success": _ok(""), "partial": _warn(""), "failed": _err("")}.get(status, "  ")
                timestamp = entry.get("timestamp", "")
                print(f"  {icon} {BOLD}{entry.get('node', '?'):<32}{RESET} | evidence={entry.get('evidence_count', 0):<4} | duration={entry.get('duration_ms', 0):>6,}ms | {_dim(timestamp[11:19] if timestamp else '')}")

        def _print_errors(self, output):
            if not output.errors:
                return
            print(_h2(f"ERRORS ({len(output.errors)})"))
            for err in output.errors:
                print(f"  {_warn('')} [{err.get('node', '?')}][{err.get('field', '?')}]")
                print(_wrap(err.get("message", "?"), indent=6))

        def _print_footer(self, output):
            print(f"\n{'═' * 62}")
            status_line = {"success": _ok(f"Run COMPLETE — {output.run_id}"), "partial": _warn(f"Run PARTIAL — {output.run_id}"), "failed": _err(f"Run FAILED — {output.run_id}")}.get(output.status, f"Run {output.run_id}")
            print(f"  {status_line}")
            print(f"{'═' * 62}\n")

    # ── Async runner ──────────────────────────────────────────────────────
    async def _pipeline() -> int:
        print(_h1("CONTENT CREATOR AGENT"))
        print(f"  Starting at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        missing_vars = _check_environment()
        if missing_vars:
            for var in missing_vars:
                print(_err(f"Missing required environment variable: {var}"))
            print("\n  Set these in your .env file or shell environment.\n  See .env.example for reference.\n")
            return 1

        print(_ok("Environment variables verified"))

        memory = get_session_memory()
        if memory.has_runs():
            print(_h2(f"SESSION HISTORY ({len(memory)} previous run(s))"))
            print(memory.summary())
            print()

        try:
            config = _collect_brand_input()
        except KeyboardInterrupt:
            print(_warn("\nInput cancelled by user."))
            return 1

        agent: ContentCreatorAgent = ContentCreatorAgent()
        output: ContentCreatorOutput | None = None

        try:
            print(f"  {BOLD}Running Content Creator Agent...{RESET}")
            print(_dim("  This typically takes 30–120 seconds depending on model and network.\n"))

            start  = asyncio.get_event_loop().time()
            output = await agent.run(**config)
            elapsed = asyncio.get_event_loop().time() - start
            print(_ok(f"Agent completed in {elapsed:.1f}s\n"))
            memory.add(output, config)

        except ValueError as exc:
            print(_err(f"Input validation error: {exc}"))
            return 1
        except RuntimeError as exc:
            print(_err(f"Agent runtime error: {exc}"))
            logger.exception("Unrecoverable agent error")
            return 1
        except KeyboardInterrupt:
            print(_warn("\nRun interrupted by user."))
            return 1
        except Exception as exc:
            print(_err(f"Unexpected error: {exc}"))
            logger.exception("Unexpected error in content creator main()")
            return 1

        OutputPrinter(quiet=quiet).print_all(output, config)

        if memory.has_runs() and len(memory) > 1:
            print(_h2(f"SESSION HISTORY ({len(memory)} runs this session)"))
            print(memory.summary())
            print()

        if save_output and output:
            try:
                filepath = _save_output(output, config)
                print(_ok(f"Output saved to: {BOLD}{filepath}{RESET}"))
            except Exception as exc:
                print(_warn(f"Could not save output: {exc}"))

        if output.status in ("success", "partial") and (output.generated_posts or output.campaign_ideas):
            await run_chat_loop(output=output, config=config)

        return 1 if output.status == "failed" else 0

    return asyncio.run(_pipeline())


# ===========================================================================
# Entry point
# ===========================================================================

def _parse_args() -> argparse.Namespace:
    """
    Parses optional CLI flags. Mode selection always happens interactively,
    but Content Creator flags can be pre-supplied on the command line.
    """
    parser = argparse.ArgumentParser(
        description="AgenticApp — BrandGenius & Content Creator Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python main.py                        # interactive mode selector
          python main.py --quiet                # content creator: summary only
          python main.py --save-output          # content creator: save JSON
          python main.py --quiet --save-output
        """),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="[Mode 2 only] Print run summary only — skip full content output.",
    )
    parser.add_argument(
        "--save-output",
        action="store_true",
        dest="save_output",
        help="[Mode 2 only] Save full output to ./outputs/<brand>_<timestamp>.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    mode = _select_mode()

    if mode == 1:
        _run_brandgenius()
    else:
        exit_code = _run_content_creator(
            quiet=args.quiet,
            save_output=args.save_output,
        )
        sys.exit(exit_code)