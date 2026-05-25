import asyncio
import sys
import logging
from dotenv import load_dotenv
from config.settings import settings
from agents.research_agent import AutonomousResearchAgent
from agents.analyst_agent import BrandAnalystAgent
from nodes.analyst_node import generate_positioning_statement
from utils.brand_brief import collect_brand_brief
from utils.positioning_map import render_positioning_map
from config.llm_factory import get_primary_llm

load_dotenv()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("research_agent.main")


async def main() -> None:
    print("=" * 70)
    print("BRANDGENIUS — MARKET RESEARCH + BRAND ANALYSIS")
    print("=" * 70)

    try:
        user_idea = input("\nEnter your startup or business idea description:\n> ").strip()
        if not user_idea:
            print("Error: Business idea cannot be empty.")
            return

        # Brand Brief Questions — collect before research runs
        brand_brief = collect_brand_brief(user_idea)

        # Stage 1 — Market Research
        print("\n[Stage 1] Running market research...")
        print("(This may take a minute. Please hold.)\n")
        research_agent = AutonomousResearchAgent()
        research_result = await research_agent.execute_research(idea=user_idea)

        final_report = research_result.get("final_report", "")
        insights = research_result.get("insights", [])

        print("\n" + "=" * 70)
        print("MARKET RESEARCH REPORT")
        print("=" * 70)
        print(final_report)

        # Stage 2 — Brand Analysis
        print("\n[Stage 2] Running full brand positioning analysis...")
        print("(Enriching competitors with real reviews and web data. Please hold.)\n")

        # Enrich idea with client brief answers
        enriched_idea = (
            f"{user_idea}\n"
            f"Client differentiator: {brand_brief.differentiator}\n"
            f"Ideal customer: {brand_brief.ideal_customer}\n"
            f"Non-negotiable: {brand_brief.non_negotiable}"
        )

        analyst = BrandAnalystAgent()
        analysis = await analyst.execute_analysis(
            idea=enriched_idea,
            research_report=final_report,
            insights=insights
        )

        print("\n" + "=" * 70)
        print("BRAND POSITIONING ANALYSIS")
        print("=" * 70)

        # Positioning Map — visual first
        print("\n## Competitive Positioning Map")
        print(render_positioning_map(analysis))

        print(f"\n## Positioning Axes")
        print(f"  Axis 1: {analysis.positioning_axes.axis_1_label} "
              f"({analysis.positioning_axes.axis_1_low} → {analysis.positioning_axes.axis_1_high})")
        print(f"  Axis 2: {analysis.positioning_axes.axis_2_label} "
              f"({analysis.positioning_axes.axis_2_low} → {analysis.positioning_axes.axis_2_high})")
        print(f"  Why: {analysis.positioning_axes.reasoning}")

        print(f"\n## Competitor Profiles ({len(analysis.competitors)} enriched)")
        for c in analysis.competitors:
            print(f"\n  {c.name} — {c.rating}/5 ({c.review_count} reviews) [{c.data_confidence} confidence]")
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

        # Positioning Statement — bridge to strategy writer
        print("\n[Generating positioning statement...]\n")
        llm = get_primary_llm()
        statement = await generate_positioning_statement(
            idea=enriched_idea,
            analysis=analysis,
            llm=llm
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

        print("\n" + "=" * 70)
        print("Operation completed successfully.")

    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
    except Exception as err:
        print(f"\nPipeline error: {str(err)}")
        logger.error("Runtime error.", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
