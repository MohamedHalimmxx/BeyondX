import logging
import httpx
from tavily import AsyncTavilyClient
from config.settings import settings

logger = logging.getLogger("research_agent.tools.competitor_enricher")

PLACES_REVIEWS_URL = "https://places.googleapis.com/v1/{place_id}"
PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


async def get_place_reviews(place_name: str, location: str) -> str:
    """
    Fetches real customer reviews for a competitor using Google Places API.
    Returns raw review text for the LLM to analyze.
    """
    api_key = settings.GOOGLE_PLACES_API_KEY.get_secret_value()

    # First find the place ID
    search_headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.rating"
    }
    search_body = {
        "textQuery": f"{place_name} {location}",
        "maxResultCount": 1
    }

    async with httpx.AsyncClient() as client:
        search_response = await client.post(
            PLACES_SEARCH_URL,
            headers=search_headers,
            json=search_body
        )

    places = search_response.json().get("places", [])
    if not places:
        return f"No Google Places data found for {place_name}."

    place_id = places[0].get("id", "")
    if not place_id:
        return f"Could not retrieve place ID for {place_name}."

    # Fetch reviews using the place ID
    review_headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "reviews"
    }

    async with httpx.AsyncClient() as client:
        review_response = await client.get(
            f"https://places.googleapis.com/v1/places/{place_id}",
            headers=review_headers
        )

    review_data = review_response.json()
    reviews = review_data.get("reviews", [])

    if not reviews:
        return f"No reviews found for {place_name}."

    compiled = []
    for review in reviews[:5]:  # top 5 reviews
        rating = review.get("rating", "")
        text = review.get("text", {}).get("text", "")
        if text:
            compiled.append(f"Rating: {rating}/5 — {text}")

    return f"Customer reviews for {place_name}:\n" + "\n\n".join(compiled)


async def search_competitor_online(competitor_name: str, location: str, category: str) -> str:
    """
    Searches for online presence, pricing signals, and brand information
    for a competitor using Tavily.
    Works for any business type in any location.
    """
    api_key = settings.TAVILY_API_KEY.get_secret_value()
    client = AsyncTavilyClient(api_key=api_key)

    query = f'"{competitor_name}" {location} {category} menu prices reviews brand'

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            max_results=3,
            include_raw_content=False
        )

        results = response.get("results", [])
        if not results:
            return f"No online data found for {competitor_name}."

        compiled = []
        for item in results:
            url = item.get("url", "")
            content = item.get("content", "")
            if content:
                compiled.append(f"[SOURCE: {url}]\n{content}")

        return f"Online presence data for {competitor_name}:\n" + "\n\n---\n\n".join(compiled)

    except Exception as exc:
        logger.error(f"Tavily search failed for {competitor_name}: {str(exc)}")
        return f"Online search failed for {competitor_name}: {str(exc)}"


async def enrich_competitor(
    name: str,
    rating: float,
    review_count: int,
    location: str,
    category: str
) -> dict:
    """
    Enriches a single competitor with real data from Google Places reviews
    and Tavily web search.

    Returns a dict with all enrichment data ready for the analyst LLM.
    """
    logger.info(f"Enriching competitor: {name}")

    reviews_data = await get_place_reviews(
        place_name=name,
        location=location
    )

    online_data = await search_competitor_online(
        competitor_name=name,
        location=location,
        category=category
    )

    return {
        "name": name,
        "rating": rating,
        "review_count": review_count,
        "reviews_data": reviews_data,
        "online_data": online_data
    }
