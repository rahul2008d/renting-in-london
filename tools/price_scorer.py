from __future__ import annotations

import json
import math

from strands import tool

from data.area_profiles import get_profile
from data.london_areas import get_zone, get_zone_from_address, search_areas


WEIGHT_PRESETS = {
    "balanced": {
        "price": 0.30,
        "space": 0.20,
        "location": 0.20,
        "commute": 0.15,
        "amenity": 0.15,
    },
    "budget": {
        "price": 0.50,
        "space": 0.20,
        "location": 0.10,
        "commute": 0.10,
        "amenity": 0.10,
    },
    "commute": {
        "price": 0.15,
        "space": 0.10,
        "location": 0.25,
        "commute": 0.40,
        "amenity": 0.10,
    },
    "space": {
        "price": 0.20,
        "space": 0.40,
        "location": 0.15,
        "commute": 0.15,
        "amenity": 0.10,
    },
    "amenities": {
        "price": 0.15,
        "space": 0.10,
        "location": 0.20,
        "commute": 0.15,
        "amenity": 0.40,
    },
}

ZONE_SCORES = {
    1: 90.0,
    2: 80.0,
    3: 60.0,
    4: 40.0,
    5: 20.0,
}


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _extract_properties(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        props = payload.get("properties")
        if isinstance(props, list):
            return [item for item in props if isinstance(item, dict)]
        top_picks = payload.get("top_picks")
        trade_offs = payload.get("with_trade_offs")
        if isinstance(top_picks, list) or isinstance(trade_offs, list):
            combined = (top_picks or []) + (trade_offs or [])
            return [item for item in combined if isinstance(item, dict)]

    return []


def _resolve_area_name(address: str) -> str | None:
    if not address:
        return None
    matches = search_areas(address)
    if not matches:
        return None
    first = matches[0]
    if isinstance(first, dict) and isinstance(first.get("name"), str):
        return first["name"]
    return None


def _price_score(price: float, min_price: float, max_price: float) -> float:
    if max_price <= min_price:
        return 100.0
    score = 100.0 - (((price - min_price) / (max_price - min_price)) * 100.0)
    return max(0.0, min(100.0, score))


def _space_score(bedrooms: int, property_type: str, price: float) -> float:
    base = min(100.0, max(10.0, bedrooms * 22.0))

    normalized_type = (property_type or "").lower()
    if "house" in normalized_type:
        type_bonus = 15.0
    elif "flat" in normalized_type:
        type_bonus = 8.0
    elif "studio" in normalized_type:
        type_bonus = -8.0
    else:
        type_bonus = 0.0

    price_pressure = min(25.0, max(0.0, (price - 1500.0) / 120.0))
    score = base + type_bonus - price_pressure
    return max(0.0, min(100.0, score))


def _location_score(zone: int) -> float:
    return ZONE_SCORES.get(zone, 20.0)


def _commute_score(
    latitude: float,
    longitude: float,
    workplace_lat: float,
    workplace_lon: float,
) -> tuple[float, float | None]:
    if workplace_lat == 0.0 and workplace_lon == 0.0:
        return 50.0, None

    if latitude == 0.0 and longitude == 0.0:
        return 30.0, None

    distance_km = _haversine_km(latitude, longitude, workplace_lat, workplace_lon)
    score = 100.0 - min(100.0, (distance_km / 30.0) * 100.0)
    return max(0.0, min(100.0, score)), distance_km


def _amenity_score(area_name: str | None) -> float:
    if not area_name:
        return 45.0

    profile = get_profile(area_name)
    if not isinstance(profile, dict):
        return 45.0

    amenity_fields = [
        "restaurants",
        "indian_groceries",
        "fish_shops",
        "supermarkets",
        "green_space",
        "transport",
    ]
    filled_fields = 0
    richness_score = 0.0

    for field in amenity_fields:
        value = profile.get(field)
        if isinstance(value, str) and value.strip():
            filled_fields += 1
            richness_score += min(20.0, len(value.strip()) / 10.0)

    base = (filled_fields / len(amenity_fields)) * 70.0
    score = base + min(30.0, richness_score / len(amenity_fields))
    return max(0.0, min(100.0, score))


@tool
def score_properties(
    properties_json: str,
    workplace_lat: float = 0.0,
    workplace_lon: float = 0.0,
    priorities: str = "balanced",
) -> str:
    """Score and rank rental properties on value-for-money dimensions.

    Args:
        properties_json: JSON string from search_london_rentals (top_picks + with_trade_offs).
        workplace_lat: Optional workplace latitude for commute proxy scoring.
        workplace_lon: Optional workplace longitude for commute proxy scoring.
        priorities: Scoring weight preset: balanced, budget, commute, space, or amenities.

    Returns:
        JSON string with ranked properties and per-dimension scores (0-100) plus
        weighted total score. Includes applied weight preset and summary metadata.
        Returns JSON error payload if input is invalid.
    """
    if not properties_json or not properties_json.strip():
        return json.dumps({"error": "properties_json is required."})

    normalized_priorities = (priorities or "balanced").strip().lower()
    if normalized_priorities not in WEIGHT_PRESETS:
        normalized_priorities = "balanced"
    weights = WEIGHT_PRESETS[normalized_priorities]

    try:
        payload = json.loads(properties_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "properties_json is not valid JSON."})

    properties = _extract_properties(payload)
    if not properties:
        return json.dumps(
            {
                "priorities": normalized_priorities,
                "weights": weights,
                "total_properties": 0,
                "ranked_properties": [],
            }
        )

    prices = [
        _to_float(prop.get("price_pcm"), 0.0)
        for prop in properties
        if _to_float(prop.get("price_pcm"), 0.0) > 0
    ]
    min_price = min(prices) if prices else 0.0
    max_price = max(prices) if prices else 0.0

    ranked: list[dict] = []
    for prop in properties:
        price = _to_float(prop.get("price_pcm"), 0.0)
        bedrooms = _to_int(prop.get("bedrooms"), 0)
        property_type = str(prop.get("property_type") or "")
        address = str(prop.get("address") or "")
        latitude = _to_float(prop.get("latitude"), 0.0)
        longitude = _to_float(prop.get("longitude"), 0.0)

        area_name = _resolve_area_name(address)
        zone = prop.get("zone") if isinstance(prop.get("zone"), int) else get_zone_from_address(address)

        price_score = _price_score(price, min_price, max_price)
        space_score = _space_score(bedrooms, property_type, price)
        location_score = _location_score(zone)
        commute_score, commute_distance_km = _commute_score(
            latitude,
            longitude,
            workplace_lat,
            workplace_lon,
        )
        amenity_score = _amenity_score(area_name)

        total_score = (
            price_score * weights["price"]
            + space_score * weights["space"]
            + location_score * weights["location"]
            + commute_score * weights["commute"]
            + amenity_score * weights["amenity"]
        )

        ranked.append(
            {
                "id": prop.get("id"),
                "url": prop.get("url"),
                "address": address,
                "area": area_name,
                "zone": zone,
                "price_pcm": price,
                "bedrooms": bedrooms,
                "property_type": property_type,
                "scores": {
                    "price": round(price_score, 1),
                    "space": round(space_score, 1),
                    "location": round(location_score, 1),
                    "commute": round(commute_score, 1),
                    "amenity": round(amenity_score, 1),
                },
                "commute_distance_km": (
                    round(commute_distance_km, 2)
                    if isinstance(commute_distance_km, float)
                    else None
                ),
                "total_score": round(total_score, 2),
            }
        )

    ranked.sort(key=lambda item: item["total_score"], reverse=True)

    return json.dumps(
        {
            "priorities": normalized_priorities,
            "weights": weights,
            "total_properties": len(ranked),
            "ranked_properties": ranked,
        }
    )
