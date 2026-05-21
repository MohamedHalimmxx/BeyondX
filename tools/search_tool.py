import logging
from typing import Any
from tavily import AsyncTavilyClient
from config.settings import settings

logger = logging.getLogger("research_agent.tools.search_tool")


class MarketSearchTool:
    """Wrapper class for executing async web intelligence queries safely."""

    def __init__(self) -> None:
        """Initializes the underlying search infrastructure."""
        api_key = settings.TAVILY_API_KEY.get_secret_value() if hasattr(settings, "TAVILY_API_KEY") else None
        if not api_key:
            logger.warning("TAVILY_API_KEY missing from environment configuration. Tool calls may fail.")
        self.client = AsyncTavilyClient(api_key=api_key)

    async def run_async(self, query: str, max_results: int = 5) -> str:
        """Executes a search query and yields a clean text payload of raw contexts.
        
        Args:
            query: The precise lookup string targeted by the agent.
            max_results: Upper bounds threshold of documents retrieved.
        """
        if not query.strip():
            return "Empty search query submitted. No findings collected."

        try:
            logger.info(f"Dispatching tool query request: '{query}'")
            response = await self.client.search(
                query=query,
                search_depth="advanced",
                max_results=max_results,
                include_raw_content=False
            )
            
            results = response.get("results", [])
            if not results:
                return f"No visual or documentary results found for query: '{query}'."

            # clean data blob
            compiled_findings = []
            for item in results:
                title = item.get("title", "No Title")
                url = item.get("url", "No URL")
                content = item.get("content", "")
                compiled_findings.append(f"Source: {title} ({url})\nFindings: {content}\n---")

            return "\n\n".join(compiled_findings)

        except Exception as exc:
            logger.error(f"Transient error encountered within search tool infrastructure: {str(exc)}", exc_info=True)
            return f"Search execution failed due to system exception: {str(exc)}"