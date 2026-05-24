import asyncio
import sys
import logging
from dotenv import load_dotenv
from config.settings import settings
from agents.research_agent import AutonomousResearchAgent
from agents.analyst_agent import BrandAnalystAgent

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
        print("\n[Stage 2] Running brand positioning analysis...")
        analyst = BrandAnalystAgent()
        analysis = await analyst.execute_analysis(
            idea=user_idea,
            research_report=final_report,
            insights=insights
        )

        print("\n" + "=" * 70)
        print("BRAND POSITIONING ANALYSIS")
        print("=" * 70)

        print("\n## Competitor Positioning Map")
        for c in analysis.competitors:
            print(f"\n  {c.name}")
            print(f"    Premium:    {c.premium_score}/10")
            print(f"    Innovation: {c.innovation_score}/10")
            print(f"    Strength:   {c.strength}")
            print(f"    Weakness:   {c.weakness}")

        print(f"\n## White Space\n{analysis.white_space}")

        print("\n## Customer Pain Points")
        for p in analysis.pain_points:
            print(f"\n  [{p.theme}]")
            print(f"  Problem:     {p.description}")
            print(f"  Opportunity: {p.opportunity}")

        print(f"\n## Positioning Recommendation\n{analysis.positioning_recommendation}")

        print("\n" + "=" * 70)
        print("Operation completed successfully.")

    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
    except Exception as err:
        print(f"\nPipeline error: {str(err)}")
        logger.error("Runtime error.", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
