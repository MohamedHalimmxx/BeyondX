"""Competitor enricher — fetches real reviews and online presence data."""

import logging
import httpx
from tavily import AsyncTavilyClient
from config.settings import settings

logger = logging.getLogger("research_agent.tools.competitor_enricher")

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAIL_URL = "https://places.googleapis.com/v1/places/{place_id}"


async def get_place_data(place_name: str, location: str) -> dict:
    """Fetch rating, review count, and reviews from Google Places."""
    api_key = settings.GOOGLE_PLACES_API_KEY.get_secret_value()

    search_headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.rating,places.userRatingCount",
    }
    search_body = {"textQuery": f"{place_name} {location}", "maxResultCount": 1}

    async with httpx.AsyncClient() as client:
        search_resp = await client.post(
            PLACES_SEARCH_URL, headers=search_headers, json=search_body
        )

    places = search_resp.json().get("places", [])
    if not places:
        return {"found": False, "rating": 0.0, "review_count": 0, "reviews_text": ""}

    place = places[0]
    place_id = place.get("id", "")
    rating = float(place.get("rating", 0.0))
    review_count = int(place.get("userRatingCount", 0))

    review_headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "reviews",
    }
    async with httpx.AsyncClient() as client:
        detail_resp = await client.get(
            PLACES_DETAIL_URL.format(place_id=place_id),
            headers=review_headers,
        )

    reviews = detail_resp.json().get("reviews", [])
    compiled = []
    for r in reviews[:5]:
        r_rating = r.get("rating", "")
        text = r.get("text", {}).get("text", "")
        if text:
            compiled.append(f"Rating: {r_rating}/5 — {text}")

    return {
        "found": True,
        "rating": rating,
        "review_count": review_count,
        "reviews_text": "\n\n".join(compiled),
    }


async def search_competitor_online(
    competitor_name: str, location: str, category: str
) -> str:
    """Tavily web search for pricing signals, brand info, online presence."""
    api_key = settings.TAVILY_API_KEY.get_secret_value()
    client = AsyncTavilyClient(api_key=api_key)
    query = f'"{competitor_name}" {location} {category} menu prices reviews brand'

    try:
        response = await client.search(
            query=query, search_depth="basic", max_results=3, include_raw_content=False
        )
        results = response.get("results", [])
        if not results:
            return f"No online data found for {competitor_name}."
        compiled = [
            f"[SOURCE: {r.get('url', '')}]\n{r.get('content', '')}"
            for r in results if r.get("content")
        ]
        return f"Online presence data for {competitor_name}:\n" + "\n\n---\n\n".join(compiled)
    except Exception as exc:
        logger.error(f"Tavily search failed for {competitor_name}: {exc}")
        return f"Online search failed for {competitor_name}."


async def enrich_competitor(
    name: str,
    rating: float,
    review_count: int,
    location: str,
    category: str,
    has_physical_location: bool = True,
) -> dict:
    """
    Enrich a competitor with real data.
    - Physical businesses: Google Places (rating + reviews) + Tavily (online presence)
    - Digital/SaaS businesses: Tavily only (no Places lookup)
    Rating and review_count are resolved from Places when available.
    """
    logger.info(f"Enriching competitor: {name}")

    resolved_rating = rating
    resolved_review_count = review_count
    reviews_text = ""

    if has_physical_location:
        place_data = await get_place_data(place_name=name, location=location)
        if place_data["found"]:
            resolved_rating = place_data["rating"]
            resolved_review_count = place_data["review_count"]
            reviews_text = place_data["reviews_text"]
            if not reviews_text:
                logger.info(f"No Places reviews for {name} — supplementing with Tavily.")
                reviews_text = await search_competitor_online(name, location, category)
        else:
            logger.info(f"No Places data for {name} — falling back to Tavily web search.")
            reviews_text = await search_competitor_online(name, location, category)
    else:
        # Digital/SaaS competitor — skip Places entirely
        reviews_text = await search_competitor_online(name, location, category)

    # Single Tavily call for online presence (separate from reviews)
    online_data = await search_competitor_online(name, location, category)

    if resolved_review_count == 0 and "No online data" in online_data:
        data_note = "WARNING: No review data or online data found. Scores based on inference only."
    elif resolved_review_count == 0:
        data_note = "NOTE: No Google reviews found. Scores based on web search data only."
    else:
        data_note = f"Data from {resolved_review_count} reviews (rating: {resolved_rating}/5)."

    return {
        "name": name,
        "rating": resolved_rating,
        "review_count": resolved_review_count,
        "reviews_data": reviews_text,
        "online_data": online_data,
        "data_note": data_note,
    }