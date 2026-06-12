"""
Brand pipeline router.

POST /api/brand/run
    Accepts brand brief, streams stage-by-stage progress via SSE,
    returns final brand pack as JSON.

GET /api/brand/result/{run_id}
    Returns the saved result for a completed run.
"""

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger("beyondx.api.brand")

router = APIRouter()

# ── In-memory result store (keyed by run_id) ─────────────────────────────────
_results: dict[str, dict] = {}


# ── Request schema ────────────────────────────────────────────────────────────

class BrandBriefRequest(BaseModel):
    idea: str
    location: str
    differentiator: str
    ideal_customer: str
    non_negotiable: str


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Main pipeline generator ───────────────────────────────────────────────────

async def _run_pipeline(run_id: str, req: BrandBriefRequest) -> AsyncGenerator[str, None]:
    """
    Runs the full BrandGenius pipeline and yields SSE events at each stage.
    """
    try:
        # ── imports (deferred so API starts fast) ────────────────────────────
        from config.settings import settings
        from agents.research_agent import AutonomousResearchAgent
        from agents.analyst_agent import BrandAnalystAgent
        from agents.strategy_agent import StrategyWriterAgent
        from agents.naming_agent import BrandNamingAgent
        from agents.brand_identity_agent import BrandIdentityAgent
        from agents.visual_identity_agent import VisualIdentityAgent
        from agents.brand_book_agent import BrandBookAgent
        from agents.lovable_agent import LovableAgent
        from nodes.analyst_node import generate_positioning_statement
        from config.llm_factory import get_primary_llm
        from utils.brand_brief import ClientBrandBrief as BrandBrief
        from utils.positioning_map import render_positioning_map

        yield _sse("start", {"run_id": run_id, "total_stages": 8})

        location_context = f" in {req.location}" if req.location != "Not specified" else ""
        research_idea = f"{req.idea}{location_context}"
        enriched_idea = (
            f"{req.idea}{location_context}\n"
            f"Client differentiator: {req.differentiator}\n"
            f"Ideal customer: {req.ideal_customer}\n"
            f"Non-negotiable: {req.non_negotiable}"
        )
        brand_brief = BrandBrief(
            idea=req.idea,
            location=req.location,
            differentiator=req.differentiator,
            ideal_customer=req.ideal_customer,
            non_negotiable=req.non_negotiable,
        )

        # ── Stage 1 — Market Research ─────────────────────────────────────────
        yield _sse("stage_start", {"stage": 1, "name": "Market research", "detail": "Scanning competitors and market data"})
        research_agent = AutonomousResearchAgent()
        research_result = await research_agent.execute_research(idea=research_idea)
        final_report = research_result.get("report", research_result.get("final_report", ""))
        gathered_data = research_result.get("gathered_data", [])
        insights = research_result.get("insights", [])
        yield _sse("stage_done", {"stage": 1, "name": "Market research"})

        # ── Stage 2 — Brand Analysis ──────────────────────────────────────────
        yield _sse("stage_start", {"stage": 2, "name": "Brand positioning", "detail": "Mapping competitors and identifying white spaces"})
        analyst = BrandAnalystAgent()
        research_report = final_report if final_report else "\n".join(gathered_data)
        if len(research_report) > 8000:
            research_report = research_report[:8000] + "\n[... truncated ...]"
        analysis = await analyst.execute_analysis(
            idea=enriched_idea,
            research_report=research_report,
            insights=insights[:20],
        )
        llm = get_primary_llm()
        statement = await generate_positioning_statement(
            idea=enriched_idea, analysis=analysis, llm=llm
        )
        yield _sse("stage_done", {"stage": 2, "name": "Brand positioning"})

        # ── Stage 3 — Strategy ────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": 3, "name": "Go-to-market strategy", "detail": "Building 90-day launch playbook"})
        strategist = StrategyWriterAgent()
        strategy_playbook, strategy_plan = await strategist.generate_plan({
            "idea": enriched_idea,
            "research_report": final_report,
            "positioning_statement": statement.full_statement,
            "positioning_map_ascii": render_positioning_map(analysis),
        })
        yield _sse("stage_done", {"stage": 3, "name": "Go-to-market strategy"})

        # ── Stage 4 — Naming ──────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": 4, "name": "Brand naming", "detail": "Generating candidates and checking domains"})
        naming_agent = BrandNamingAgent()
        naming_output = await naming_agent.generate_names(
            idea=enriched_idea,
            positioning_statement=statement.full_statement,
            analysis=analysis,
            brand_brief=brand_brief,
        )
        yield _sse("stage_done", {"stage": 4, "name": "Brand naming"})

        # ── Stage 5 — Identity ────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": 5, "name": "Brand identity", "detail": "Writing mission, origin story, voice and values"})
        identity_agent = BrandIdentityAgent()
        identity = await identity_agent.generate_identity(
            idea=enriched_idea,
            positioning_statement=statement.full_statement,
            naming_output=naming_output,
            analysis=analysis,
            brand_brief=brand_brief,
        )
        yield _sse("stage_done", {
            "stage": 5,
            "name": "Brand identity",
            "brand_name": identity.selected_name,
        })

        brand_safe = identity.selected_name.lower().replace(" ", "_")
        brand_pack_dir = Path("brand_packs") / brand_safe

        # ── Stage 6 — Visual Identity ─────────────────────────────────────────
        yield _sse("stage_start", {"stage": 6, "name": "Visual identity", "detail": "Generating color palette, typography and logos"})
        visual = None
        try:
            visual_agent = VisualIdentityAgent()
            visual = await visual_agent.generate_visual_identity(
                brand_name=identity.selected_name,
                identity=identity,
                analysis=analysis,
                output_dir=brand_pack_dir,
            )
            yield _sse("stage_done", {
                "stage": 6,
                "name": "Visual identity",
                "logo_count": len(visual.logo_paths),
                "colors": [{"name": c.name, "hex": c.hex, "role": c.role} for c in visual.colors],
            })
        except Exception as e:
            logger.warning(f"Stage 6 failed: {e}")
            yield _sse("stage_warning", {"stage": 6, "name": "Visual identity", "message": str(e)[:100]})

        
        # ── Stage 7 — Brand Experience ────────────────────────────────────────
        yield _sse("stage_start", {"stage": 7, "name": "Brand experience", "detail": "Building premium HTML brand document"})
        brand_book_path = None
        if visual:
            try:
                brand_book_agent = BrandBookAgent()
                brand_book_path = await brand_book_agent.generate(
                    brand_name=identity.selected_name,
                    identity=identity,
                    analysis=analysis,
                    strategy=strategy_plan,
                    naming=naming_output,
                    visual=visual,
                    output_dir=brand_pack_dir,
                )
                yield _sse("stage_done", {"stage": 7, "name": "Brand experience", "path": str(brand_book_path)})
            except Exception as e:
                logger.warning(f"Stage 7 failed: {e}")
                yield _sse("stage_warning", {"stage": 7, "name": "Brand experience", "message": str(e)[:100]})
        else:
            yield _sse("stage_warning", {"stage": 7, "name": "Brand experience", "message": "Skipped — visual identity incomplete"})

        # ── Stage 8 — Lovable ─────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": 8, "name": "Live web app", "detail": "Generating Lovable app prompt"})
        lovable_url = None
        try:
            lovable = LovableAgent()
            lovable_url = lovable.generate_url(
                brand_name=identity.selected_name,
                identity=identity,
                analysis=analysis,
                strategy=strategy_plan,
                naming=naming_output,
                visual=visual,
            )
            lovable.save_url(lovable_url, identity.selected_name, brand_pack_dir)
            lovable.save_claude_code_prompt(
                brand_name=identity.selected_name,
                identity=identity,
                analysis=analysis,
                strategy=strategy_plan,
                naming=naming_output,
                visual=visual,
                output_dir=brand_pack_dir,
            )
            yield _sse("stage_done", {"stage": 8, "name": "Live web app", "lovable_url": lovable_url})
        except Exception as e:
            logger.warning(f"Stage 8 failed: {e}")
            yield _sse("stage_warning", {"stage": 8, "name": "Live web app", "message": str(e)[:100]})

        # ── Build final result payload ─────────────────────────────────────────
        result = {
            "run_id": run_id,
            "brand_name": identity.selected_name,
            "tagline": identity.tagline,
            "mission": identity.mission,
            "positioning": statement.full_statement,
            "origin_story": identity.origin_story,
            "personality_traits": identity.personality_traits,
            "brand_voice_is": identity.brand_voice_is,
            "core_values": identity.core_values,
            "competitors": [
                {
                    "name": c.name,
                    "axis_1_score": c.axis_1_score,
                    "axis_2_score": c.axis_2_score,
                    "pricing_tier": c.pricing_tier,
                }
                for c in analysis.competitors
            ],
            "white_spaces": [ws.description for ws in analysis.white_spaces],
            "pain_points": [{"theme": p.theme, "description": p.description} for p in analysis.pain_points],
            "positioning_axes": {
                "axis_1_label": analysis.positioning_axes.axis_1_label,
                "axis_1_low": analysis.positioning_axes.axis_1_low,
                "axis_1_high": analysis.positioning_axes.axis_1_high,
                "axis_2_label": analysis.positioning_axes.axis_2_label,
                "axis_2_low": analysis.positioning_axes.axis_2_low,
                "axis_2_high": analysis.positioning_axes.axis_2_high,
            },
            "top_names": [
                {"name": c.name, "score": c.score, "domain_com": c.domain_com, "domain_io": c.domain_io}
                for c in naming_output.candidates[:5]
            ],
            "colors": [{"name": c.name, "hex": c.hex, "role": c.role, "rationale": c.rationale} for c in visual.colors] if visual else [],
            "typography": {
                "primary_font": visual.typography.primary_font,
                "secondary_font": visual.typography.secondary_font,
            } if visual else {},
            "logo_paths": visual.logo_paths if visual else [],
            "brand_book_path": f"/brand-packs/{brand_safe}/{Path(brand_book_path).name}" if brand_book_path else None,
            "lovable_url": lovable_url,
            "strategy_playbook": strategy_playbook,
        }

        _results[run_id] = result
        yield _sse("complete", result)

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        yield _sse("error", {"message": str(e)})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_brand_pipeline(req: BrandBriefRequest):
    """Start the brand pipeline and stream progress via SSE."""
    run_id = str(uuid.uuid4())

    return StreamingResponse(
        _run_pipeline(run_id, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/result/{run_id}")
async def get_result(run_id: str):
    """Return the saved result for a completed run."""
    if run_id not in _results:
        return {"error": "Run not found"}
    return _results[run_id]