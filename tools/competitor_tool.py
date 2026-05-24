import logging
import httpx
from config.settings import settings

logger = logging.getLogger("research_agent.tools.competitor_tool")

PLACES_NEW_URL = "https://places.googleapis.com/v1/places:searchText"


async def find_local_competitors(category: str, location: str) -> str:
    """
    Finds actual businesses in the target location using Google Places API (New).
    Returns real business names, ratings, and addresses.
    """
    api_key = settings.GOOGLE_PLACES_API_KEY.get_secret_value()
    query = f"{category} in {location}"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount"
    }

    body = {"textQuery": query, "maxResultCount": 8}

    async with httpx.AsyncClient() as client:
        response = await client.post(PLACES_NEW_URL, headers=headers, json=body)

    data = response.json()
    places = data.get("places", [])

    if not places:
        logger.warning(f"No results from Google Places for: '{query}'")
        return f"No local competitors found for '{category}' in '{location}'."

    compiled = []
    for place in places:
        name = place.get("displayName", {}).get("text", "Unknown")
        address = place.get("formattedAddress", "No address")
        rating = place.get("rating", "No rating")
        total_ratings = place.get("userRatingCount", 0)
        compiled.append(
            f"Business: {name}\n"
            f"Address: {address}\n"
            f"Rating: {rating}/5 ({total_ratings} reviews)\n---"
        )

    return "\n\n".join(compiled)
