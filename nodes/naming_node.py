"""Brand Naming Node — generates, validates, and evaluates brand name candidates."""

import asyncio
import logging
import json
from typing import cast
from langchain_core.language_models.chat_models import BaseChatModel
from groq import RateLimitError

from state.naming_state import BrandNamingOutput
from prompts.naming_prompts import NAMING_SYSTEM_PROMPT, NAMING_HUMAN_TEMPLATE
from config.llm_factory import get_fallback_llm, get_primary_llm

logger = logging.getLogger("research_agent.nodes.naming_node")


async def check_domain(name: str) -> dict:
    """
    Checks domain availability using DNS lookup.
    No paid API required.
    """
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


async def validate_brand_conflicts(
    candidates: list,
    llm: BaseChatModel
) -> dict:
    """
    Uses LLM knowledge to check if any candidate name is already
    a well-known brand, celebrity, product, or cultural figure.

    Step 1: LLM knowledge check for all names in one call.
    Step 2: Tavily search for names flagged as uncertain.

    Returns dict: {name: {"status": "conflict/clear/unknown", "reason": "..."}}
    """
    name_list = [c.name for c in candidates]

    # Step 1 — LLM knowledge check
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
        raw = response.content
        # Clean markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        results = {r["name"]: {"status": r["status"], "reason": r.get("reason", "")}
                   for r in data.get("results", [])}
    except Exception as e:
        logger.warning(f"LLM conflict check failed: {str(e)}. Marking all as unknown.")
        results = {name: {"status": "unknown", "reason": ""} for name in name_list}

    # Step 2 — Tavily search for uncertain names
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
                # Ask LLM to interpret the search results
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
                        "content": (
                            f"Name to check: {name}\n\n"
                            f"Search results:\n{search_results[:2000]}"
                        )
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
    structured_llm = llm.with_structured_output(BrandNamingOutput)
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
    try:
        return cast(BrandNamingOutput, await structured_llm.ainvoke(messages))
    except RateLimitError as e:
        if "tokens per day" in str(e) or "rate_limit_exceeded" in str(e):
            logger.warning("Naming Node: rate limited. Switching to fallback.")
            fallback = get_fallback_llm(temperature=0.7)
            try:
                structured_fallback = fallback.with_structured_output(BrandNamingOutput)
                return cast(BrandNamingOutput, await structured_fallback.ainvoke(messages))
            except RateLimitError as e2:
                if "tokens per day" in str(e2) or "rate_limit_exceeded" in str(e2):
                    logger.warning("Naming Node: both Groq keys exhausted. Switching to Cerebras.")
                    from config.llm_factory import get_cerebras_llm
                    from openai import RateLimitError as CerebrasRateLimitError
                    import asyncio
                    cerebras = get_cerebras_llm(temperature=0.7)
                    try:
                        structured_cerebras = cerebras.with_structured_output(BrandNamingOutput)
                        return cast(BrandNamingOutput, await structured_cerebras.ainvoke(messages))
                    except CerebrasRateLimitError:
                        logger.warning("Cerebras queue full. Retrying in 5s.")
                        await asyncio.sleep(5)
                        structured_cerebras = cerebras.with_structured_output(BrandNamingOutput)
                        return cast(BrandNamingOutput, await structured_cerebras.ainvoke(messages))
                else:
                    raise
        raise


async def naming_node(
    idea: str,
    positioning_statement: str,
    analysis,
    brand_brief,
    llm: BaseChatModel
) -> BrandNamingOutput:
    """
    Full brand naming pipeline:
    1. Generate candidates
    2. Validate brand conflicts (LLM knowledge → Tavily for uncertain)
    3. Check domain availability
    4. Return enriched output
    """
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

    # Step 2 — Conflict validation + domain check in parallel
    conflict_results = await validate_brand_conflicts(naming_output.candidates, llm)
    domain_tasks = [check_domain(c.name) for c in naming_output.candidates]
    domain_results = await asyncio.gather(*domain_tasks, return_exceptions=True)

    # Enrich candidates
    for i, candidate in enumerate(naming_output.candidates):
        # Domain
        if isinstance(domain_results[i], dict):
            candidate.domain_com = domain_results[i]["com"]
            candidate.domain_io = domain_results[i]["io"]
        # Conflict
        conflict = conflict_results.get(candidate.name, {})
        candidate.brand_conflict = conflict.get("status", "unknown")
        candidate.conflict_reason = conflict.get("reason", "")

    conflicts = sum(1 for c in naming_output.candidates if c.brand_conflict == "conflict")
    clear = sum(1 for c in naming_output.candidates if c.brand_conflict == "clear")
    logger.info(f"Naming Node complete. {clear} clear, {conflicts} conflicts, "
                f"{len(naming_output.candidates) - clear - conflicts} uncertain.")

    return naming_output
