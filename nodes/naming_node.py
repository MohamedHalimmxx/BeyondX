"""Brand Naming Node — generates, validates, and evaluates brand name candidates."""

import asyncio
import logging
import json
from typing import cast
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError

from state.naming_state import BrandNamingOutput
from prompts.naming_prompts import (
    NAMING_SYSTEM_PROMPT, NAMING_HUMAN_TEMPLATE,
    NAMING_CEREBRAS_SYSTEM_PROMPT, NAMING_CEREBRAS_HUMAN_TEMPLATE,
)
from utils.llm_utils import invoke_with_fallback, ALL_EXHAUSTED_MSG

logger = logging.getLogger("research_agent.nodes.naming_node")


async def check_domain(name: str) -> dict:
    import socket
    result = {"com": "unknown", "io": "unknown"}
    name_clean = name.lower().replace(" ", "").replace("-", "")
    for tld in ["com", "io"]:
        domain = f"{name_clean}.{tld}"
        try:
            socket.gethostbyname(domain)
            result[tld] = "taken"
        except socket.gaierror:
            result[tld] = "available"
        except Exception:
            result[tld] = "unknown"
    return result


async def _run_conflict_check(llm, name_list: list) -> dict:
    system_prompt = (
        "You are a brand trademark expert.\n"
        "For each name, check if it is already associated with a known brand, company, "
        "celebrity, or product anywhere in the world.\n"
        "Return ONLY valid JSON:\n"
        '{"results": [{"name": "...", "status": "conflict/clear/unknown", "reason": "..."}]}'
    )
    response = await llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Check these brand names:\n{json.dumps(name_list)}"},
    ])
    raw = response.content.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return {r["name"]: {"status": r["status"], "reason": r.get("reason", "")}
            for r in data.get("results", [])}


async def validate_brand_conflicts(candidates: list, llm: BaseChatModel) -> dict:
    """Check brand conflicts — Groq1 → Groq2 → Cerebras, then Tavily for uncertain names."""
    name_list = [c.name for c in candidates]

    try:
        results = await invoke_with_fallback(_run_conflict_check, llm, name_list)
    except Exception:
        logger.warning("All providers failed for conflict check. Marking all unknown.")
        results = {name: {"status": "unknown", "reason": ""} for name in name_list}

    uncertain = [n for n in name_list if results.get(n, {}).get("status") == "unknown"]
    if uncertain:
        logger.info(f"Running Tavily verification for {len(uncertain)} uncertain names.")
        from tools.search_tool import MarketSearchTool
        search_tool = MarketSearchTool()

        async def verify_one(name: str) -> tuple:
            try:
                search_results = await search_tool.run_async(
                    query=f'"{name}" brand company product trademark'
                )
                verify_prompt = (
                    "Based on these search results, is this name already used by a known brand?\n"
                    'Return ONLY JSON: {"status": "conflict/clear", "reason": "one sentence"}'
                )
                async def _verify(active_llm, name=name, search_results=search_results):
                    resp = await active_llm.ainvoke([
                        {"role": "system", "content": verify_prompt},
                        {"role": "user", "content": f"Name: {name}\n\nResults:\n{search_results[:2000]}"},
                    ])
                    raw = resp.content.replace("```json", "").replace("```", "").strip()
                    return json.loads(raw)

                verdict = await invoke_with_fallback(_verify, llm)
                return name, verdict
            except Exception:
                return name, {"status": "unknown", "reason": "verification failed"}

        verify_results = await asyncio.gather(
            *[verify_one(n) for n in uncertain], return_exceptions=True
        )
        for r in verify_results:
            if isinstance(r, tuple):
                name, verdict = r
                results[name] = verdict

    return results


def _normalize_cerebras_candidate(c: dict) -> dict:
    if "overall_score" in c and "score" not in c:
        c["score"] = c.pop("overall_score")
    c.setdefault("pronunciation_guide", "")
    c.setdefault("meaning_and_origin", "")
    c.setdefault("positioning_fit", "")
    c.setdefault("rhetorical_device", "")
    c.setdefault("domain_com", "unknown")
    c.setdefault("domain_io", "unknown")
    c.setdefault("brand_conflict", "unknown")
    c.setdefault("conflict_reason", "")
    return c


async def _groq_generate(llm, messages: list) -> BrandNamingOutput:
    structured_llm = llm.with_structured_output(BrandNamingOutput)
    return cast(BrandNamingOutput, await structured_llm.ainvoke(messages))


async def generate_brand_names(
    idea: str,
    positioning_statement: str,
    competitor_names: list[str],
    target_audience: str,
    non_negotiable: str,
    llm: BaseChatModel,
) -> BrandNamingOutput:
    template_vars = dict(
        idea=idea,
        positioning_statement=positioning_statement,
        competitor_names=", ".join(competitor_names) if competitor_names else "None identified",
        target_audience=target_audience,
        non_negotiable=non_negotiable,
    )

    groq_messages = [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": NAMING_HUMAN_TEMPLATE.format(**template_vars)},
    ]

    try:
        return await invoke_with_fallback(_groq_generate, llm, groq_messages,
                                          cerebras_temperature=0.7)
    except RuntimeError:
        pass

    # Cerebras needs its own prompt format — handle separately
    from config.llm_factory import get_cerebras_llm
    cerebras = get_cerebras_llm(temperature=0.7)
    cerebras_messages = [
        {"role": "system", "content": NAMING_CEREBRAS_SYSTEM_PROMPT},
        {"role": "user", "content": NAMING_CEREBRAS_HUMAN_TEMPLATE.format(**template_vars)},
    ]
    for attempt in range(3):
        try:
            response = await cerebras.ainvoke(cerebras_messages)
            raw = response.content.replace("```json", "").replace("```", "").strip()
            start, end = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            data["candidates"] = [_normalize_cerebras_candidate(c) for c in data.get("candidates", [])]
            return BrandNamingOutput(**data)
        except CerebrasRateLimitError:
            wait = (attempt + 1) * 15
            logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
            await asyncio.sleep(wait)
        except Exception as err:
            logger.warning(f"Cerebras naming parse failed: {err}. Retrying.")
            await asyncio.sleep(10)
    raise RuntimeError(ALL_EXHAUSTED_MSG)


async def naming_node(
    idea: str,
    positioning_statement: str,
    analysis,
    brand_brief,
    llm: BaseChatModel,
) -> BrandNamingOutput:
    logger.info("Executing Naming Node: Generating brand name candidates.")

    competitor_names = [c.name for c in analysis.competitors] if analysis.competitors else []
    target_audience = analysis.target_audience_summary

    naming_output = await generate_brand_names(
        idea=idea,
        positioning_statement=positioning_statement,
        competitor_names=competitor_names,
        target_audience=target_audience,
        non_negotiable=brand_brief.non_negotiable,
        llm=llm,
    )

    logger.info(f"Generated {len(naming_output.candidates)} candidates. Running conflict validation...")

    conflict_task = validate_brand_conflicts(naming_output.candidates, llm)
    domain_tasks = [check_domain(c.name) for c in naming_output.candidates]
    conflict_results, *domain_results = await asyncio.gather(
        conflict_task, *domain_tasks, return_exceptions=True
    )

    for i, candidate in enumerate(naming_output.candidates):
        if isinstance(domain_results[i], dict):
            candidate.domain_com = domain_results[i]["com"]
            candidate.domain_io = domain_results[i]["io"]
        if isinstance(conflict_results, dict):
            conflict = conflict_results.get(candidate.name, {})
            candidate.brand_conflict = conflict.get("status", "unknown")
            candidate.conflict_reason = conflict.get("reason", "")

    # Penalize 3+ word names — not brand names
    for candidate in naming_output.candidates:
        if len(candidate.name.split()) >= 3:
            candidate.score = min(candidate.score, 5.0)

    # Sort: clear > unknown > conflict, then by score
    def rank_key(c):
        status_rank = {"clear": 0, "unknown": 1, "conflict": 2}.get(c.brand_conflict, 1)
        return (status_rank, -c.score)

    naming_output.candidates.sort(key=rank_key)

    # Fix top_recommendation if it points to a conflicted or 3-word name
    top = naming_output.top_recommendation
    top_candidate = next((c for c in naming_output.candidates if c.name == top), None)
    if (top_candidate is None
            or top_candidate.brand_conflict == "conflict"
            or len(top_candidate.name.split()) >= 3):
        best = next(
            (c for c in naming_output.candidates
             if c.brand_conflict != "conflict" and len(c.name.split()) < 3),
            naming_output.candidates[0] if naming_output.candidates else None
        )
        if best:
            naming_output.top_recommendation = best.name
            logger.info(f"Top recommendation updated: '{top}' → '{best.name}'.")

    clear = sum(1 for c in naming_output.candidates if c.brand_conflict == "clear")
    conflicts = sum(1 for c in naming_output.candidates if c.brand_conflict == "conflict")
    logger.info(f"Naming Node complete. {clear} clear, {conflicts} conflicts, "
                f"{len(naming_output.candidates) - clear - conflicts} uncertain.")
    return naming_output