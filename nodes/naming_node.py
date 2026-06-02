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
    NAMING_SYSTEM_PROMPT,
    NAMING_HUMAN_TEMPLATE,
    NAMING_CEREBRAS_SYSTEM_PROMPT,
    NAMING_CEREBRAS_HUMAN_TEMPLATE,
)
from config.llm_factory import get_fallback_llm

logger = logging.getLogger("research_agent.nodes.naming_node")

ALL_EXHAUSTED_MSG = (
    "\n\n⚠️  All LLM providers exhausted (Groq key 1, Groq key 2, Cerebras).\n"
    "   Please wait a few minutes and run again.\n"
)


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


async def validate_brand_conflicts(candidates: list, llm: BaseChatModel) -> dict:
    """Check brand conflicts using LLM knowledge + Tavily verification.
    Falls back to Cerebras if both Groq keys are exhausted.
    """
    name_list = [c.name for c in candidates]

    system_prompt = (
        "You are a brand trademark expert.\n"
        "For each name, check if it is already associated with a known brand, company, "
        "celebrity, or product anywhere in the world.\n"
        "Return ONLY valid JSON:\n"
        '{"results": [{"name": "...", "status": "conflict/clear/unknown", "reason": "..."}]}'
    )
    user_prompt = f"Check these brand names:\n{json.dumps(name_list)}"

    async def run_conflict_check(active_llm) -> dict:
        response = await active_llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        raw = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return {r["name"]: {"status": r["status"], "reason": r.get("reason", "")}
                for r in data.get("results", [])}

    # Try Groq key 1 → key 2 → Cerebras
    results = {}
    try:
        results = await run_conflict_check(llm)
    except (RateLimitError, Exception) as e:
        logger.warning(f"LLM conflict check failed: {str(e)}. Switching to fallback.")
        try:
            results = await run_conflict_check(get_fallback_llm())
        except (RateLimitError, Exception) as e2:
            logger.warning(f"Fallback conflict check failed: {str(e2)}. Switching to Cerebras.")
            try:
                from config.llm_factory import get_cerebras_llm
                results = await run_conflict_check(get_cerebras_llm())
            except Exception:
                logger.warning("All providers failed for conflict check. Marking all unknown.")
                results = {name: {"status": "unknown", "reason": ""} for name in name_list}

    # Tavily verification for uncertain names
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
                active_llm = llm
                try:
                    resp = await active_llm.ainvoke([
                        {"role": "system", "content": verify_prompt},
                        {"role": "user", "content": f"Name: {name}\n\nResults:\n{search_results[:2000]}"}
                    ])
                except (RateLimitError, Exception):
                    from config.llm_factory import get_cerebras_llm
                    resp = await get_cerebras_llm().ainvoke([
                        {"role": "system", "content": verify_prompt},
                        {"role": "user", "content": f"Name: {name}\n\nResults:\n{search_results[:2000]}"}
                    ])
                raw = resp.content.replace("```json", "").replace("```", "").strip()
                return name, json.loads(raw)
            except Exception:
                return name, {"status": "unknown", "reason": "verification failed"}

        verify_results = await asyncio.gather(
            *[verify_one(n) for n in uncertain],
            return_exceptions=True
        )
        for r in verify_results:
            if isinstance(r, tuple):
                name, verdict = r
                results[name] = verdict

    return results


def _normalize_cerebras_candidate(c: dict) -> dict:
    """Normalize Cerebras candidate fields to match BrandNameCandidate schema."""
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

    async def try_groq(active_llm) -> BrandNamingOutput:
        structured_llm = active_llm.with_structured_output(BrandNamingOutput)
        return cast(BrandNamingOutput, await structured_llm.ainvoke(groq_messages))

    async def try_cerebras() -> BrandNamingOutput:
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

    # Groq key 1 → key 2 → Cerebras
    try:
        return await try_groq(llm)
    except RateLimitError as e:
        if "tokens per day" not in str(e) and "rate_limit_exceeded" not in str(e):
            raise

    logger.warning("Naming Node: rate limited. Switching to fallback.")
    try:
        return await try_groq(get_fallback_llm(temperature=0.7))
    except RateLimitError as e2:
        if "tokens per day" not in str(e2) and "rate_limit_exceeded" not in str(e2):
            raise

    logger.warning("Naming Node: both Groq keys exhausted. Switching to Cerebras.")
    return await try_cerebras()


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

    # Run domain checks and conflict validation in parallel
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

    clear = sum(1 for c in naming_output.candidates if c.brand_conflict == "clear")
    conflicts = sum(1 for c in naming_output.candidates if c.brand_conflict == "conflict")
    logger.info(
        f"Naming Node complete. {clear} clear, {conflicts} conflicts, "
        f"{len(naming_output.candidates) - clear - conflicts} uncertain."
    )

    return naming_output