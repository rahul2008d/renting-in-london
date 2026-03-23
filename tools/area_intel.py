from __future__ import annotations

import json

from strands import tool

from data.area_profiles import get_profile
from data.london_areas import get_zone, search_areas


@tool
def get_area_profile(area_name: str) -> str:
    """Get a structured neighbourhood profile for a London area.

    Args:
        area_name: London area to look up (supports fuzzy matching).

    Returns:
        JSON string containing full profile data when found.
        If not found, returns a JSON payload with a helpful message and similar area suggestions.
    """
    if not area_name or not area_name.strip():
        return json.dumps(
            {
                "error": "area_name is required.",
            }
        )

    cleaned_area_name = area_name.strip()
    profile = get_profile(cleaned_area_name)

    if profile is None:
        suggestions = [item.get("name") for item in search_areas(cleaned_area_name)[:5]]
        suggestions = [name for name in suggestions if isinstance(name, str)]

        return json.dumps(
            {
                "found": False,
                "area": cleaned_area_name,
                "message": "This area is not in the curated area profile database yet.",
                "suggested_areas": suggestions,
            }
        )

    result = {
        "found": True,
        "area": cleaned_area_name,
        "zone": get_zone(cleaned_area_name),
        "vibe": profile.get("vibe"),
        "avg_rent_1bed": profile.get("avg_rent_1bed"),
        "avg_rent_2bed": profile.get("avg_rent_2bed"),
        "transport": profile.get("transport"),
        "safety": profile.get("safety"),
        "green_space": profile.get("green_space"),
        "restaurants": profile.get("restaurants"),
        "indian_groceries": profile.get("indian_groceries"),
        "fish_shops": profile.get("fish_shops"),
        "supermarkets": profile.get("supermarkets"),
        "best_for": profile.get("best_for"),
        "avoid_if": profile.get("avoid_if"),
    }

    return json.dumps(result)
