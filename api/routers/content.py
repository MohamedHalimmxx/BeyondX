"""
Content Creator router.

POST /api/content/run
    Accepts brand details, streams node-by-node progress via SSE.

POST /api/content/chat
    Handles both smart intake extraction and follow-up chat.

GET /api/content/result/{run_id}
    Returns the saved result for a completed run.
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

logger = logging.getLogger("beyondx.api.content")

router = APIRouter()

_results: dict[str, dict] = {}


# ── Request schemas ───────────────────────────────────────────────────────────

class ContentRequest(BaseModel):
    brand_name: str
    industry: str
    country: str
    city: str
    foundation_date: str
    social_platforms: list[str]
    posts_per_month: int


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    output: dict | None = None        # pipeline result (for follow-up mode)
    config: dict | None = None        # brand config (for follow-up mode)
    mode: str = "intake"              # "intake" | "followup"


class ChatResponse(BaseModel):
    reply: str
    extracted: dict | None = None     # filled when all fields extracted
    ready: bool = False               # True when ready to run pipeline


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Node display names ────────────────────────────────────────────────────────

NODE_LABELS = {
    "brand_context_node":     {"name": "Brand context",    "detail": "Researching your brand and market"},
    "trend_research_node":    {"name": "Trend research",   "detail": "Finding current trends for your platforms"},
    "content_strategy_node":  {"name": "Content strategy", "detail": "Building your content pillars and mix"},
    "calendar_builder_node":  {"name": "Content calendar", "detail": "Planning your monthly schedule"},
    "content_generator_node": {"name": "Post generation",  "detail": "Writing captions and reel scripts"},
    "campaign_generator_node":{"name": "Campaigns",        "detail": "Generating campaign ideas"},
}

VALID_PLATFORMS = ["Instagram", "TikTok", "LinkedIn", "X", "Facebook", "YouTube Shorts", "Pinterest", "Threads"]


# ── Smart intake extraction ───────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You are a data extraction assistant. Extract brand information from the user's message.

Return ONLY valid JSON with these exact fields (null if not mentioned):
{
  "brand_name": string or null,
  "industry": string or null,
  "country": string or null,
  "city": string or null,
  "foundation_date": "YYYY-MM-DD" or null,
  "social_platforms": array of strings or null,
  "posts_per_month": integer or null
}

For social_platforms, only include these valid values: Instagram, TikTok, LinkedIn, X, Facebook, YouTube Shorts, Pinterest, Threads
For foundation_date, convert any date format to YYYY-MM-DD. If only year given, use YYYY-01-01.
For posts_per_month, extract any number mentioned. Default reasonable values: 12 for monthly.
Return ONLY the JSON object, no explanation."""


async def _extract_fields(message: str, existing: dict) -> dict:
    """Use LLM to extract brand fields from natural language."""
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import SystemMessage, HumanMessage

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return existing

        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.0, api_key=api_key)

        context = f"Already collected: {json.dumps({k: v for k, v in existing.items() if v})}\n\nNew message: {message}"
        response = await llm.ainvoke([
            SystemMessage(content=EXTRACTION_SYSTEM),
            HumanMessage(content=context),
        ])

        raw = response.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1])

        extracted = json.loads(raw)
        merged = dict(existing)
        for k, v in extracted.items():
            if v is not None:
                merged[k] = v
        return merged

    except Exception as e:
        logger.warning(f"Field extraction failed: {e}")
        return existing


def _missing_fields(fields: dict) -> list[str]:
    """Return list of field names that are still missing."""
    required = {
        "brand_name": "brand name",
        "industry": "industry",
        "country": "country",
        "city": "city",
        "foundation_date": "foundation date (YYYY-MM-DD)",
        "social_platforms": "social platforms",
        "posts_per_month": "posts per month",
    }
    return [label for key, label in required.items() if not fields.get(key)]


def _build_ask_message(missing: list[str], collected: dict) -> str:
    """Build a natural follow-up question for missing fields."""
    if len(missing) == 1:
        return f"Almost there! Just need one more thing — what's your {missing[0]}?"
    elif len(missing) <= 3:
        items = ", ".join(missing[:-1]) + f" and {missing[-1]}"
        return f"Got it! Could you also tell me your {items}?"
    else:
        return f"To get started, I'll need a few details: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}. What's your brand called?"


# ── Follow-up chat ────────────────────────────────────────────────────────────

async def _followup_chat(message: str, output: dict, config: dict, history: list[dict]) -> str:
    """Handle post-pipeline follow-up questions using colleague's system prompt logic."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "content_gen_agent"))

        from langchain_groq import ChatGroq
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return "Sorry, I can't connect right now. Please check your API key."

        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.4, max_tokens=3000, api_key=api_key)

        # Build system prompt with full brand context (mirrors colleague's _build_system_prompt)
        brand_name = config.get("brand_name", "")
        industry   = config.get("industry", "")
        city       = config.get("city", "")
        country    = config.get("country", "")
        platforms  = ", ".join(config.get("social_platforms", []))
        posts_pm   = config.get("posts_per_month", 0)
        foundation = config.get("foundation_date", "")

        profile   = output.get("brand_profile") or {}
        strategy  = output.get("content_strategy") or {}
        pillars   = output.get("content_pillars") or []
        posts     = output.get("generated_posts") or []
        campaigns = output.get("campaign_ideas") or []
        hashtags  = output.get("hashtag_bank") or {}
        cta_bank  = output.get("cta_bank") or []

        posts_block = "\n".join([
            f"  Post #{p.get('post_number')} | Week {p.get('week')} {p.get('day_of_week')} | "
            f"{p.get('platform')} | {p.get('content_type')} | [{p.get('content_pillar')}]\n"
            f"    Topic: {p.get('topic', 'N/A')}"
            for p in posts
        ]) or "No posts."

        pillars_block = "\n".join([
            f"  • {p.get('name')} ({p.get('percentage')}%) — {str(p.get('description', ''))[:100]}"
            for p in pillars
        ]) or "No pillars."

        campaigns_block = "\n".join([
            f"  • {c.get('name')} ({c.get('duration_days')} days) — {str(c.get('objective', ''))[:100]}"
            for c in campaigns
        ]) or "No campaigns."

        hashtag_block = "\n".join([
            f"  [{plat}][{pillar}]: {' '.join(tags[:8])}"
            for plat, pillars_map in hashtags.items()
            for pillar, tags in pillars_map.items()
        ]) or "No hashtags."

        system_prompt = f"""You are the AI Content Strategist for {brand_name}, a {industry} brand based in {city}, {country}.

You already completed a full content creation run. Answer follow-up questions, generate new content, or build next month's plan — WITHOUT asking the user to re-enter brand details.

BRAND IDENTITY
Brand Name: {brand_name} | Industry: {industry} | Location: {city}, {country}
Founded: {foundation} | Platforms: {platforms} | Posts/Month: {posts_pm}

Brand Tone: {profile.get('brand_tone', 'N/A')}
Target Audience: {profile.get('target_audience', 'N/A')}
Content Language: {profile.get('content_language', 'N/A')}
Cultural Context: {profile.get('cultural_context', 'N/A')}

STRATEGIC GOAL: {strategy.get('strategic_goal', 'N/A')}

CONTENT PILLARS:
{pillars_block}

POSTS ALREADY GENERATED ({len(posts)} posts):
{posts_block}

CAMPAIGNS:
{campaigns_block}

HASHTAG BANK:
{hashtag_block}

RULES:
1. Answer directly and concisely.
2. Generate complete, ready-to-use content — not outlines.
3. Never repeat topics already in the posts list above.
4. Write bilingually (Arabic/English) when appropriate for this brand.
5. Do not ask the user to re-enter anything — you have everything."""

        messages = [SystemMessage(content=system_prompt)]
        for turn in history[-20:]:
            if turn["role"] == "user":
                messages.append(HumanMessage(content=turn["content"]))
            elif turn["role"] == "assistant":
                messages.append(AIMessage(content=turn["content"]))
        messages.append(HumanMessage(content=message))

        response = await llm.ainvoke(messages)
        return response.content.strip()

    except Exception as e:
        logger.error(f"Follow-up chat error: {e}", exc_info=True)
        return f"Something went wrong: {str(e)[:100]}"


# ── Main content pipeline ─────────────────────────────────────────────────────

async def _run_content(run_id: str, req: ContentRequest) -> AsyncGenerator[str, None]:
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "content_gen_agent"))
        from content_gen_agent.content_creator_agent import ContentCreatorAgent

        yield _sse("start", {"run_id": run_id, "total_stages": 6})

        agent = ContentCreatorAgent()

        yield _sse("stage_start", {"stage": 1, "name": "Brand context", "detail": "Researching your brand and market"})

        output = await agent.run(
            brand_name=req.brand_name,
            industry=req.industry,
            country=req.country,
            city=req.city,
            foundation_date=req.foundation_date,
            social_platforms=req.social_platforms,
            posts_per_month=req.posts_per_month,
        )

        completed_nodes = set()
        for i, entry in enumerate(output.node_execution_log or [], 1):
            node = entry.get("node", "")
            label = NODE_LABELS.get(node, {"name": node, "detail": ""})
            if node not in completed_nodes:
                completed_nodes.add(node)
                status = entry.get("status", "success")
                event = "stage_done" if status == "success" else "stage_warning"
                yield _sse(event, {
                    "stage": i,
                    "name": label["name"],
                    "duration_ms": entry.get("duration_ms", 0),
                    "evidence_count": entry.get("evidence_count", 0),
                })

        result = {
            "run_id": run_id,
            "brand_name": req.brand_name,
            "status": output.status,
            "brand_profile": output.brand_profile,
            "content_strategy": output.content_strategy,
            "content_pillars": output.content_pillars,
            "generated_posts": output.generated_posts or [],
            "hashtag_bank": output.hashtag_bank or {},
            "cta_bank": output.cta_bank or [],
            "campaign_ideas": output.campaign_ideas or [],
            "anniversary_campaign": output.anniversary_campaign,
            "summary": output.summary,
            "errors": output.errors or [],
        }

        _results[run_id] = result
        yield _sse("complete", result)

    except Exception as e:
        logger.error(f"Content pipeline error: {e}", exc_info=True)
        yield _sse("error", {"message": str(e)})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_content_pipeline(req: ContentRequest):
    run_id = str(uuid.uuid4())
    return StreamingResponse(
        _run_content(run_id, req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/chat")
async def chat(req: ChatRequest):
    """Smart intake extraction + follow-up chat."""

    # ── Follow-up mode ────────────────────────────────────────────────────
    if req.mode == "followup" and req.output and req.config:
        reply = await _followup_chat(
            message=req.message,
            output=req.output,
            config=req.config,
            history=req.conversation_history,
        )
        return ChatResponse(reply=reply)

    # ── Intake mode — extract fields ──────────────────────────────────────
    current_fields = {}
    for turn in req.conversation_history:
        if turn.get("role") == "system" and "extracted" in turn:
            current_fields = turn["extracted"]
            break

    # Merge previously collected fields from history metadata
    for turn in req.conversation_history:
        if turn.get("extracted"):
            current_fields = {**current_fields, **turn["extracted"]}

    updated_fields = await _extract_fields(req.message, current_fields)
    missing = _missing_fields(updated_fields)

    if not missing:
        # All fields collected — ready to run
        return ChatResponse(
            reply=f"Perfect! I have everything I need. Starting your content strategy for **{updated_fields['brand_name']}** now...",
            extracted=updated_fields,
            ready=True,
        )

    reply = _build_ask_message(missing, updated_fields)
    return ChatResponse(reply=reply, extracted=updated_fields, ready=False)


@router.get("/result/{run_id}")
async def get_content_result(run_id: str):
    if run_id not in _results:
        return {"error": "Run not found"}
    return _results[run_id]