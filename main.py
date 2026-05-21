import asyncio
import sys
import logging
from dotenv import load_dotenv
from config.settings import settings
from agents.research_agent import AutonomousResearchAgent

load_dotenv()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("research_agent.main")


async def main() -> None:
    print("=" * 70)
    print("MARKET RESEARCH AGENT")
    print("=" * 70)
    
    try:
        user_idea = input("\nEnter your startup or business idea description:\n> ").strip()
        if not user_idea:
            print("Error: Business concept payload parameters cannot be empty values.")
            return

        print("\n[Thinking] Initializing agent execution context layers...")
        agent = AutonomousResearchAgent()
        
        print("\n[Running] Research agent is compiling blueprints and hunting data...")
        print("          (This loops through discovery data iteratively. Please hold.)\n")
        
        result = await agent.execute_research(idea=user_idea)
        
        report = result.get("final_report", "# Execution Error\nReport synthesis missing from output payload.")
        
        print("\n" + "=" * 70)
        print("GENERATED MARKET RESEARCH REPORT")
        print("=" * 70 + "\n")
        print(report)
        print("\n" + "=" * 70)
        print("Operation completed successfully.")
        
    except KeyboardInterrupt:
        print("\n\n Execution cancelled by user interruption. Shutting down system nodes cleanly.")
    except Exception as err:
        print(f"\n Pipeline breakdown structural event encountered during execution trace: {str(err)}")
        logger.error("Core runtime breakdown exception logged.", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())