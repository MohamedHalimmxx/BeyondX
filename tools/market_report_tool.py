import logging
from tavily import AsyncTavilyClient
from config.settings import settings

logger = logging.getLogger("research_agent.tools.market_report_tool")

# These domains consistently return real market data for MENA/Egypt
REPORT_DOMAINS = [
    "mordorintelligence.com",
    "statista.com",
    "marketresearch.com",
    "businessresearchinsights.com",
    "grandviewresearch.com",
    "futuremarketinsights.com"
]


class MarketReportTool:
    """Tavily search restricted to known market research domains."""

    def __init__(self) -> None:
        api_key = settings.TAVILY_API_KEY.get_secret_value()
        self.client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str) -> str:
        try:
            response = await self.client.search(
                query=query,
                search_depth="advanced",
                max_results=5,
                include_domains=REPORT_DOMAINS,
                include_raw_content=False
            )

            results = response.get("results", [])
            if not results:
                return "No market report data found for this query."

            compiled = []
            for item in results:
                title = item.get("title", "No Title")
                url = item.get("url", "No URL")
                content = item.get("content", "")
                compiled.append(f"[SOURCE: {url}]\nTitle: {title}\nFindings: {content}\n---")

            return "\n\n".join(compiled)

        except Exception as exc:
            logger.error(f"Market report search failed: {str(exc)}")
            return f"Market report search failed: {str(exc)}"