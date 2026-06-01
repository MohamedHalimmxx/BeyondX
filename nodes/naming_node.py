"""Brand Naming Node — generates, validates, and evaluates brand name candidates."""

import asyncio
import logging
import json
from typing import cast
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError
from openai import RateLimitError as CerebrasRateLimitError

from state.naming_state import BrandNamingOutput
from prompts.naming_prompts import NAMING_SYSTEM_PROMPT, NAMING_HUMAN_TEMPLATE
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
    name_list = [c.name for c in candidates]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a brand trademark expert with comprehensive knowledge of "
                "global brands, companies, celebrities, products, and cultural figures.\n\n"
                "For each brand name provided, check from your knowledge whether it is "
                "already associated with an existing well-known brand, company, celebrity, "
                "product, or cultural figure anywhere in the world.\n\n"
                "Be honest about uncertainty — if you are not sure, say 'unknown'.\n\n"
                "Return ONLY a valid JSON object with this exact structure:\n"
                '{"results": [{"name": "...", "status": "conflict/clear/unknown", "reason": "..."}]}\n\n'
                "Status meanings:\n"
                "- conflict: this name is clearly already used by a known brand or figure\n"
                "- clear: to your knowledge this name is not used by any known brand\n"
                "- unknown: you are not certain either way"
            )
        },
        {
            "role": "user",
            "content": f"Check these brand name candidates:\n{json.dumps(name_list)}"
        }
    ]

    try:
        response = await llm.ainvoke(messages)
        raw = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        results = {r["name"]: {"status": r["status"], "reason": r.get("reason", "")}
                   for r in data.get("results", [])}
    except Exception as e:
        logger.warning(f"LLM conflict check failed: {str(e)}. Marking all as unknown.")
        results = {name: {"status": "unknown", "reason": ""} for name in name_list}

    uncertain_names = [name for name in name_list
                       if results.get(name, {}).get("status") == "unknown"]

    if uncertain_names:
        logger.info(f"Running Tavily verification for {len(uncertain_names)} uncertain names.")
        from tools.search_tool import MarketSearchTool
        search_tool = MarketSearchTool()

        async def verify_name(name: str) -> tuple:
            try:
                search_results = await search_tool.run_async(
                    query=f'"{name}" brand company product trademark'
                )
                verify_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Based on the search results provided, determine if this name "
                            "is already used by a well-known brand, company, or product.\n"
                            "Answer with ONLY valid JSON: "
                            '{"status": "conflict/clear", "reason": "one sentence"}'
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Name to check: {name}\n\nSearch results:\n{search_results[:2000]}"
                    }
                ]
                verify_response = await llm.ainvoke(verify_messages)
                raw = verify_response.content.replace("```json", "").replace("```", "").strip()
                verdict = json.loads(raw)
                return name, verdict
            except Exception:
                return name, {"status": "unknown", "reason": "verification failed"}

        verify_tasks = [verify_name(name) for name in uncertain_names]
        verify_results = await asyncio.gather(*verify_tasks, return_exceptions=True)

        for result in verify_results:
            if isinstance(result, tuple):
                name, verdict = result
                results[name] = verdict

    return results


async def generate_brand_names(
    idea: str,
    positioning_statement: str,
    competitor_names: list[str],
    target_audience: str,
    non_negotiable: str,
    llm: BaseChatModel
) -> BrandNamingOutput:
    messages = [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": NAMING_HUMAN_TEMPLATE.format(
            idea=idea,
            positioning_statement=positioning_statement,
            competitor_names=", ".join(competitor_names) if competitor_names else "None identified",
            target_audience=target_audience,
            non_negotiable=non_negotiable
        )}
    ]

    async def try_groq(active_llm):
        structured_llm = active_llm.with_structured_output(BrandNamingOutput)
        return cast(BrandNamingOutput, await structured_llm.ainvoke(messages))

    async def try_cerebras():
        from config.llm_factory import get_cerebras_llm
        cerebras = get_cerebras_llm(temperature=0.7)
        json_messages = [
            {
                "role": "system",
                "content": NAMING_SYSTEM_PROMPT + (
                    "\n\nIMPORTANT: Return ONLY valid JSON matching this exact schema, "
                    "no markdown, no explanation:\n"
                    '{"candidates": [...], "top_recommendation": "...", '
                    '"naming_strategy": "...", "names_to_avoid": []}'
                )
            },
            messages[1]
        ]
        for attempt in range(3):
            try:
                response = await cerebras.ainvoke(json_messages)
                raw = response.content.replace("```json", "").replace("```", "").strip()
                data = json.loads(raw)
                # Cerebras uses different field names — normalize
                for c in data.get("candidates", []):
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
                return BrandNamingOutput(**data)
            except CerebrasRateLimitError:
                wait = (attempt + 1) * 15
                logger.warning(f"Cerebras queue full. Retrying in {wait}s (attempt {attempt+1}/3).")
                await asyncio.sleep(wait)
            except Exception as parse_err:
                logger.warning(f"Cerebras naming parse failed: {parse_err}. Retrying.")
                await asyncio.sleep(10)
        raise RuntimeError(ALL_EXHAUSTED_MSG)

    # Groq key 1
    try:
        return await try_groq(llm)
    except RateLimitError as e:
        if "tokens per day" not in str(e) and "rate_limit_exceeded" not in str(e):
            raise

    # Groq key 2
    logger.warning("Naming Node: rate limited. Switching to fallback.")
    try:
        return await try_groq(get_fallback_llm(temperature=0.7))
    except RateLimitError as e2:
        if "tokens per day" not in str(e2) and "rate_limit_exceeded" not in str(e2):
            raise

    # Cerebras
    logger.warning("Naming Node: both Groq keys exhausted. Switching to Cerebras.")
    return await try_cerebras()


async def naming_node(
    idea: str,
    positioning_statement: str,
    analysis,
    brand_brief,
    llm: BaseChatModel
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
        llm=llm
    )

    logger.info(f"Generated {len(naming_output.candidates)} candidates. Running conflict validation...")

    conflict_results = await validate_brand_conflicts(naming_output.candidates, llm)
    domain_tasks = [check_domain(c.name) for c in naming_output.candidates]
    domain_results = await asyncio.gather(*domain_tasks, return_exceptions=True)

    for i, candidate in enumerate(naming_output.candidates):
        if isinstance(domain_results[i], dict):
            candidate.domain_com = domain_results[i]["com"]
            candidate.domain_io = domain_results[i]["io"]
        conflict = conflict_results.get(candidate.name, {})
        candidate.brand_conflict = conflict.get("status", "unknown")
        candidate.conflict_reason = conflict.get("reason", "")

    conflicts = sum(1 for c in naming_output.candidates if c.brand_conflict == "conflict")
    clear = sum(1 for c in naming_output.candidates if c.brand_conflict == "clear")
    logger.info(f"Naming Node complete. {clear} clear, {conflicts} conflicts, "
                f"{len(naming_output.candidates) - clear - conflicts} uncertain.")

    return naming_output