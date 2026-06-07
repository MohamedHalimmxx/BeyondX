"""Strategy Writer Node — generates the Go-To-Market playbook."""

import logging
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel

from state.strategy_state import StrategicGoToMarketPlan
from prompts.strategy_prompts import (
    STRATEGY_GENERATOR_SYSTEM_PROMPT,
    STRATEGY_GENERATOR_HUMAN_TEMPLATE,
)
from utils.llm_utils import invoke_with_fallback

logger = logging.getLogger("research_agent.nodes.strategy_node")


def compile_markdown_brief(
    plan: StrategicGoToMarketPlan,
    statement: str,
    map_ascii: str,
) -> str:
    md = f"""# COMPREHENSIVE GO-TO-MARKET STRATEGY WORKBOOK

## 1. Brand Positioning Anchor

**Core Positioning Statement:**

> {statement}

### Competitive Layout Map

```text
{map_ascii}
```

## 2. Core Messaging Framework

**Primary Launch Tagline:**

"{plan.messaging_framework.primary_tagline}"

### Value Proposition Copywriting Hooks

"""
    for hook in plan.messaging_framework.value_prop_hooks:
        md += f"* {hook}\n"

    md += "\n### Brand Voice & Expression Guidelines:\n"
    for rule in plan.messaging_framework.brand_voice_guidelines:
        md += f"- {rule}\n"

    md += "\n---\n\n## 3. Targeted Channel Matrix\n"
    for chan in plan.channel_matrix:
        md += f"### {chan.channel_name} | Weight: **{chan.allocation_weight}**\n"
        md += f"* **Execution Blueprint:** {chan.execution_strategy}\n\n"

    md += "---\n\n## 4. 90-Day Tactical Launch Roadmap\n"
    for phase in plan.ninety_day_launch_roadmap:
        md += f"### {phase.phase_name}\n"
        md += f"* **Core Objective:** {phase.strategic_objective}\n"
        md += "* **Tactical Actions:**\n"
        for act in phase.tactical_actions:
            md += f"  - {act}\n"
        md += "* **Success Metrics / KPIs:**\n"
        for kpi in phase.kpis_to_track:
            md += f"  - {kpi}\n"
        md += "\n"

    md += "---\n\n## 5. Creative Content Pillars\n"
    for pillar in plan.creative_content_pillars:
        md += f"* **Pillar Theme:** {pillar}\n"

    md += (
        "\n---\n\n"
        "## 6. Operational Defensive Moat Strategy\n"
        f"{plan.defensive_moat_strategy}\n"
    )
    return md


async def _run_strategy(llm: BaseChatModel, state: dict) -> StrategicGoToMarketPlan:
    structured_llm = llm.with_structured_output(StrategicGoToMarketPlan)
    messages = [
        {
            "role": "system",
            "content": (
                STRATEGY_GENERATOR_SYSTEM_PROMPT
                + "\n\nIMPORTANT: Return ONLY valid JSON output."
                + "\nThe output MUST follow the provided schema."
            ),
        },
        {
            "role": "user",
            "content": STRATEGY_GENERATOR_HUMAN_TEMPLATE.format(
                idea=state.get("idea", ""),
                research_report=state.get("final_report", state.get("research_report", "")),
                positioning_statement=state.get("positioning_statement", ""),
                positioning_map_ascii=state.get("positioning_map_ascii", ""),
            ),
        },
    ]
    return cast(StrategicGoToMarketPlan, await structured_llm.ainvoke(messages))


async def strategy_node(
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    logger.info("Executing Strategy Node: Generating custom Go-To-Market blueprint.")

    llm: BaseChatModel | None = config.get("configurable", {}).get("llm")
    if llm is None:
        raise KeyError("LLM must be injected into graph configuration.")

    validated_plan = await invoke_with_fallback(_run_strategy, llm, state)

    final_brief_text = compile_markdown_brief(
        plan=validated_plan,
        statement=state.get("positioning_statement", ""),
        map_ascii=state.get("positioning_map_ascii", ""),
    )

    logger.info("Strategy Node successfully built and formatted strategy brief.")
    return {"final_strategic_brief": final_brief_text, "validated_plan": validated_plan}