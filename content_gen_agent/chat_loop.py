from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_TEMPERATURE: float = 0.4
LLM_MAX_TOKENS: int = 3000

EXIT_COMMANDS: frozenset[str] = frozenset(
    {"exit", "quit", "done", "bye", "stop", "q"}
)

# ---------------------------------------------------------------------------
# ANSI helpers (duplicated from main.py to keep this module self-contained)
# ---------------------------------------------------------------------------

def _supports_colour() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

RESET  = "\033[0m"  if _supports_colour() else ""
BOLD   = "\033[1m"  if _supports_colour() else ""
GREEN  = "\033[32m" if _supports_colour() else ""
YELLOW = "\033[33m" if _supports_colour() else ""
CYAN   = "\033[36m" if _supports_colour() else ""
DIM    = "\033[2m"  if _supports_colour() else ""
MAGENTA= "\033[35m" if _supports_colour() else ""

def _h2(text: str) -> str:
    return f"\n{BOLD}{YELLOW}── {text} {'─' * max(0, 55 - len(text))}{RESET}"

def _dim(text: str) -> str:
    return f"{DIM}{text}{RESET}"

def _user_prompt() -> str:
    return f"\n{BOLD}{GREEN}You{RESET} → "

def _agent_prefix() -> str:
    return f"\n{BOLD}{CYAN}Agent{RESET} → "


# ---------------------------------------------------------------------------
# System prompt builder
# Injects the full session context so the LLM knows everything already done.
# ---------------------------------------------------------------------------

def _build_system_prompt(
    output: Any,          # ContentCreatorOutput
    config: dict[str, Any],
    conversation_history: list[dict[str, str]],
) -> str:
    """
    Builds the system prompt for follow-up conversations.

    Includes:
    - Brand identity and profile
    - Content strategy and pillars
    - Full list of generated post topics (with post numbers)
    - Campaign names and objectives
    - Hashtag bank summary
    - Instructions for handling different follow-up types
    """
    brand_name = config.get("brand_name", "")
    industry   = config.get("industry", "")
    city       = config.get("city", "")
    country    = config.get("country", "")
    platforms  = ", ".join(config.get("social_platforms", []))
    posts_pm   = config.get("posts_per_month", 0)
    foundation = config.get("foundation_date", "")

    # ── Brand profile ─────────────────────────────────────────────────────
    profile = output.brand_profile or {}
    profile_block = (
        f"Brand Tone       : {profile.get('brand_tone', 'N/A')}\n"
        f"Target Audience  : {profile.get('target_audience', 'N/A')}\n"
        f"Content Language : {profile.get('content_language', 'N/A')}\n"
        f"Cultural Context : {profile.get('cultural_context', 'N/A')}\n"
        f"Unique Value Prop: {profile.get('unique_value_prop', 'N/A')}\n"
        f"Market Position  : {profile.get('market_positioning', 'N/A')}"
    )

    # ── Strategy ──────────────────────────────────────────────────────────
    strategy = output.content_strategy or {}
    strategic_goal    = strategy.get("strategic_goal", "N/A")
    audience_insight  = strategy.get("audience_insight", "N/A")

    tone_guidelines = strategy.get("tone_guidelines", {})
    tone_voice    = tone_guidelines.get("overall_voice", "N/A")
    tone_language = tone_guidelines.get("language_style", "N/A")
    tone_culture  = tone_guidelines.get("cultural_adaptations", "N/A")

    platform_strategy = strategy.get("platform_strategy", {})
    platform_lines = []
    for plat, details in platform_strategy.items():
        platform_lines.append(
            f"  {plat}: {details.get('role', 'N/A')} | "
            f"Frequency: {details.get('posting_frequency', 'N/A')} | "
            f"Formats: {', '.join(details.get('best_formats', []))}"
        )
    platform_block = "\n".join(platform_lines) or "N/A"

    content_mix = strategy.get("content_mix", {})
    mix_block = " | ".join(
        f"{k}: {v}%"
        for k, v in content_mix.items()
        if isinstance(v, (int, float)) and k != "note"
    ) or "N/A"

    # ── Pillars ───────────────────────────────────────────────────────────
    pillar_lines = []
    for p in (output.content_pillars or []):
        pillar_lines.append(
            f"  • {p.get('name')} ({p.get('percentage')}%) — "
            f"{p.get('description', '')[:100]}"
        )
    pillars_block = "\n".join(pillar_lines) or "N/A"

    # ── Generated posts (topic list) ──────────────────────────────────────
    post_lines = []
    for post in (output.generated_posts or []):
        post_lines.append(
            f"  Post #{post.get('post_number')} | "
            f"Week {post.get('week')} {post.get('day_of_week')} | "
            f"{post.get('platform')} | {post.get('content_type')} | "
            f"[{post.get('content_pillar')}]\n"
            f"    Topic: {post.get('topic', 'N/A')}"
        )
    posts_block = "\n".join(post_lines) or "No posts generated."

    # ── Campaigns ─────────────────────────────────────────────────────────
    campaign_lines = []
    for c in (output.campaign_ideas or []):
        campaign_lines.append(
            f"  • {c.get('name')} ({c.get('duration_days')} days | "
            f"{', '.join(c.get('platforms', []))})\n"
            f"    Objective: {c.get('objective', 'N/A')[:120]}\n"
            f"    Hashtag  : {c.get('hashtag', 'N/A')}"
        )
    campaigns_block = "\n".join(campaign_lines) or "No campaigns generated."

    anniversary = output.anniversary_campaign
    anniversary_block = (
        f"  Name     : {anniversary.get('campaign_name', 'N/A')}\n"
        f"  Theme    : {anniversary.get('theme', 'N/A')}\n"
        f"  Hashtag  : {anniversary.get('hashtag', 'N/A')}\n"
        f"  Date     : {anniversary.get('anniversary_date', 'N/A')}"
        if anniversary else "  None generated."
    )

    # ── Hashtag bank ─────────────────────────────────────────────────────
    hashtag_lines = []
    for plat, pillars in (output.hashtag_bank or {}).items():
        for pillar, tags in pillars.items():
            hashtag_lines.append(
                f"  [{plat}][{pillar}]: {' '.join(tags[:8])}"
            )
    hashtag_block = "\n".join(hashtag_lines) or "N/A"

    # ── Conversation turns so far ────────────────────────────────────────
    turns = len(conversation_history)

    return f"""You are the AI Content Strategist for {brand_name}, a {industry} brand based in {city}, {country}.

You have already completed a full content creation run for this brand this session.
Your job now is to answer follow-up questions, generate additional content, refine
existing content, or produce next-month plans — all WITHOUT asking the user to
re-enter brand details. You already have everything you need below.

{'═' * 60}
BRAND IDENTITY
{'═' * 60}
Brand Name      : {brand_name}
Industry        : {industry}
Location        : {city}, {country}
Founded         : {foundation}
Platforms       : {platforms}
Posts/Month     : {posts_pm}

BRAND PROFILE
{profile_block}

{'═' * 60}
CONTENT STRATEGY (THIS MONTH)
{'═' * 60}
Strategic Goal  : {strategic_goal}
Audience Insight: {audience_insight}
Content Mix     : {mix_block}

TONE GUIDELINES
  Voice    : {tone_voice}
  Language : {tone_language}
  Culture  : {tone_culture}

PLATFORM STRATEGY
{platform_block}

{'═' * 60}
CONTENT PILLARS
{'═' * 60}
{pillars_block}

{'═' * 60}
POSTS ALREADY GENERATED ({len(output.generated_posts or [])} posts)
{'═' * 60}
{posts_block}

{'═' * 60}
CAMPAIGNS ALREADY GENERATED
{'═' * 60}
{campaigns_block}

ANNIVERSARY CAMPAIGN
{anniversary_block}

{'═' * 60}
HASHTAG BANK
{'═' * 60}
{hashtag_block}

{'═' * 60}
CONVERSATION CONTEXT
{'═' * 60}
This is turn {turns + 1} of the follow-up conversation.
The user already knows their brand details — do NOT ask them to re-enter anything.
Do NOT re-introduce yourself or summarise what was generated unless asked.

RESPONSE RULES
──────────────
1. Answer directly and concisely — this is a conversational interface.
2. When generating new content (posts, campaigns, strategies), produce
   complete, ready-to-use output — not outlines or placeholders.
3. When generating next month content, build on this month's strategy.
   Use the same pillars and tone but with fresh topics — do NOT repeat
   any topic already in the posts list above.
4. When asked for captions, hashtags, or scripts — write them fully,
   not descriptions of what they would contain.
5. Keep responses focused — do not dump the entire session context back
   unless the user asks for a summary.
6. If the user asks something outside content strategy scope, gently
   redirect to what you can help with.
7. Format your output clearly — use line breaks, labels, and structure
   appropriate to the content type being generated.
8. Always respect the brand's content language ({profile.get('content_language', 'AR/EN')}) —
   if bilingual, write bilingually where appropriate.
"""


# ---------------------------------------------------------------------------
# LLM client factory
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set.")
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Single conversation turn
# ---------------------------------------------------------------------------

async def _chat_turn(
    user_message: str,
    system_prompt: str,
    conversation_history: list[dict[str, str]],
    llm: ChatGroq,
) -> str:
    """
    Sends one user message to the LLM with full conversation history
    and returns the assistant response string.

    Parameters
    ----------
    user_message : str
        The user's latest input.
    system_prompt : str
        Full system prompt with injected session context.
    conversation_history : list[dict[str, str]]
        Previous turns as [{"role": "user"|"assistant", "content": str}].
    llm : ChatGroq
        Authenticated LLM client.

    Returns
    -------
    str
        The assistant's response text.
    """
    # Build message list: system + full history + new user message
    messages = [SystemMessage(content=system_prompt)]

    for turn in conversation_history:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    messages.append(HumanMessage(content=user_message))

    response = await llm.ainvoke(messages)
    return response.content.strip()


# ---------------------------------------------------------------------------
# Suggestion generator
# Shown to the user after the first run so they know what they can ask.
# ---------------------------------------------------------------------------

def _generate_suggestions(output: Any, config: dict[str, Any]) -> list[str]:
    """Generates context-aware follow-up suggestions based on what was produced."""
    suggestions = []
    brand = config.get("brand_name", "your brand")
    platforms = config.get("social_platforms", [])

    suggestions.append("Give me next month's content strategy and calendar")

    if platforms:
        p = platforms[0]
        suggestions.append(f"Generate 5 more posts for {p}")

    suggestions.append("Create a campaign for the upcoming holiday season")

    if output.content_pillars:
        pillar = output.content_pillars[0].get("name", "")
        if pillar:
            suggestions.append(f"Write 3 captions for the '{pillar}' pillar")

    suggestions.append("What topics haven't we covered yet?")
    suggestions.append("Give me 15 new hashtags for Instagram")
    suggestions.append("Rewrite the caption for post 1 in a more casual tone")
    suggestions.append("Summarise everything generated this session")

    return suggestions[:6]


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def run_chat_loop(
    output: Any,
    config: dict[str, Any],
) -> None:
    """
    Runs the interactive follow-up chat loop.

    Called by main.py immediately after the first agent run completes.
    The loop continues until the user types an exit command.

    Parameters
    ----------
    output : ContentCreatorOutput
        The completed agent output from the first run.
    config : dict
        The brand configuration used for the first run.
    """
    print(_h2("FOLLOW-UP MODE — Ask anything about your content"))
    print(
        f"  {_dim('Your brand context is loaded. No need to re-enter anything.')}\n"
        f"  {_dim('Type your question and press Enter. Type exit to finish.')}\n"
    )

    # Show context-aware suggestions
    suggestions = _generate_suggestions(output, config)
    print(f"  {BOLD}Try asking:{RESET}")
    for i, s in enumerate(suggestions, 1):
        print(f"  {_dim(str(i) + '.')} {s}")

    print()

    # Initialise LLM and conversation history
    try:
        llm = _get_llm()
    except EnvironmentError as exc:
        print(f"  Cannot start chat: {exc}")
        return

    conversation_history: list[dict[str, str]] = []
    turn_count = 0

    while True:
        # ── Get user input ─────────────────────────────────────────────
        try:
            sys.stdout.write(_user_prompt())
            sys.stdout.flush()
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {_dim('Session ended.')}")
            break

        if not user_input:
            continue

        if user_input.lower() in EXIT_COMMANDS:
            print(f"\n  {_dim('Session ended. Goodbye!')}")
            break

        # ── Check shortcut numbers (user types 1-6 to pick suggestion) ──
        if user_input.isdigit() and 1 <= int(user_input) <= len(suggestions):
            user_input = suggestions[int(user_input) - 1]
            print(f"  {_dim('→ ' + user_input)}")

        # ── Build system prompt (rebuilt each turn to include latest state)
        system_prompt = _build_system_prompt(
            output=output,
            config=config,
            conversation_history=conversation_history,
        )

        # ── Call LLM ───────────────────────────────────────────────────
        print(f"  {_dim('Thinking...')}", end="", flush=True)

        try:
            response = await _chat_turn(
                user_message=user_input,
                system_prompt=system_prompt,
                conversation_history=conversation_history,
                llm=llm,
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            is_rate_limit = "429" in err or "rate_limit" in err.lower()
            print("\r" + " " * 20 + "\r", end="")  # clear "Thinking..."
            if is_rate_limit:
                print(
                    f"  {YELLOW}⚠{RESET} Groq rate limit reached. "
                    f"Wait a moment and try again."
                )
            else:
                print(f"  {YELLOW}⚠{RESET} Error: {err[:120]}")
            continue

        # Clear "Thinking..." and print response
        print("\r" + " " * 20 + "\r", end="")
        print(_agent_prefix())
        print()

        # Print response with indentation for readability
        for line in response.split("\n"):
            print(f"  {line}")

        print()

        # ── Update conversation history ────────────────────────────────
        conversation_history.append({"role": "user",      "content": user_input})
        conversation_history.append({"role": "assistant", "content": response})
        turn_count += 1

        # ── Keep history bounded (last 10 turns = 20 messages) ─────────
        # Prevents context window overflow on long sessions
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        # ── Re-show suggestions every 5 turns ─────────────────────────
        if turn_count % 5 == 0:
            print(f"  {_dim('Need ideas? Try: ' + ' | '.join(suggestions[:3]))}")
            print()
