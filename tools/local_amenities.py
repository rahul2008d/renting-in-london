from __future__ import annotations

import json
import math
import time

import httpx
from strands import tool


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_RESULTS_PER_CATEGORY = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

INDIAN_GROCERY_QUERY = """
[out:json][timeout:25];
(
  node["shop"="supermarket"]["name"~"Indian|Asian|Desi|Patel|Spice",i](around:{radius},{lat},{lon});
  node["shop"="convenience"]["name"~"Indian|Asian|Desi|Patel|Spice",i](around:{radius},{lat},{lon});
  node["shop"="grocery"]["name"~"Indian|Asian|Desi|Patel|Spice",i](around:{radius},{lat},{lon});
);
out body;
""".strip()

RESTAURANT_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="restaurant"](around:{radius},{lat},{lon});
  node["amenity"="fast_food"](around:{radius},{lat},{lon});
  node["amenity"="cafe"](around:{radius},{lat},{lon});
);
out body;
""".strip()

FISH_SHOP_QUERY = """
[out:json][timeout:25];
(
  node["shop"="seafood"](around:{radius},{lat},{lon});
  node["shop"="fishmonger"](around:{radius},{lat},{lon});
  node["name"~"Fish",i](around:{radius},{lat},{lon});
);
out body;
""".strip()

SUPERMARKET_QUERY = """
[out:json][timeout:25];
(
  node["shop"="supermarket"](around:{radius},{lat},{lon});
);
out body;
""".strip()

QUERY_MAP = {
    "indian_grocery": INDIAN_GROCERY_QUERY,
    "restaurant": RESTAURANT_QUERY,
    "fish_shop": FISH_SHOP_QUERY,
    "supermarket": SUPERMARKET_QUERY,
}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in metres between two WGS84 coordinates."""
    radius_earth_m = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_earth_m * c


def _parse_elements(
    elements: list,
    latitude: float,
    longitude: float,
) -> list[dict]:
    parsed: list[dict] = []

    for element in elements:
        if not isinstance(element, dict):
            continue

        element_lat = element.get("lat")
        element_lon = element.get("lon")
        if not isinstance(element_lat, (int, float)) or not isinstance(
            element_lon, (int, float)
        ):
            continue

        tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}

        house_number = tags.get("addr:housenumber", "")
        street = tags.get("addr:street", "")
        address = " ".join(str(part) for part in [house_number, street] if part).strip()

        parsed.append(
            {
                "name": tags.get("name", "Unnamed"),
                "type": tags.get("shop") or tags.get("amenity", "unknown"),
                "cuisine": tags.get("cuisine", ""),
                "address": address,
                "lat": element_lat,
                "lon": element_lon,
                "distance_m": round(
                    haversine(latitude, longitude, float(element_lat), float(element_lon)),
                    1,
                ),
            }
        )

    parsed.sort(key=lambda item: item["distance_m"])
    return parsed[:MAX_RESULTS_PER_CATEGORY]


def _run_query(
    client: httpx.Client,
    query_template: str,
    latitude: float,
    longitude: float,
    radius_metres: int,
) -> list[dict]:
    query = query_template.format(radius=radius_metres, lat=latitude, lon=longitude)
    response = client.post(OVERPASS_URL, data={"data": query})
    response.raise_for_status()

    payload = response.json()
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        return []

    return _parse_elements(elements, latitude, longitude)


@tool
def find_nearby_amenities(
    latitude: float,
    longitude: float,
    amenity_type: str = "all",
    radius_metres: int = 1000,
) -> str:
    """Find nearby amenities around a property using OpenStreetMap Overpass API.

    Args:
        latitude: Property latitude.
        longitude: Property longitude.
        amenity_type: One of "indian_grocery", "restaurant", "fish_shop",
            "supermarket", or "all".
        radius_metres: Search radius in metres.

    Returns:
        JSON string containing categorized, distance-sorted amenity results.
        For amenity_type="all", returns results for all four categories.
        On error, returns JSON with an "error" key.
    """
    normalized_type = (amenity_type or "all").strip().lower()
    if normalized_type not in QUERY_MAP and normalized_type != "all":
        return json.dumps(
            {
                "error": (
                    "Invalid amenity_type. Use one of: indian_grocery, restaurant, "
                    "fish_shop, supermarket, all."
                )
            }
        )

    safe_radius = max(100, min(int(radius_metres), 5000))
    categories = list(QUERY_MAP.keys()) if normalized_type == "all" else [normalized_type]

    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            results: dict[str, list[dict]] = {}
            for category_index, category in enumerate(categories):
                query_template = QUERY_MAP[category]
                results[category] = _run_query(
                    client=client,
                    query_template=query_template,
                    latitude=latitude,
                    longitude=longitude,
                    radius_metres=safe_radius,
                )
                if category_index < len(categories) - 1:
                    time.sleep(1.0)

    except httpx.TimeoutException:
        return json.dumps(
            {
                "error": "Overpass API request timed out.",
                "amenity_type": normalized_type,
                "radius_metres": safe_radius,
            }
        )
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {
                "error": f"Overpass API returned HTTP {exc.response.status_code}.",
                "amenity_type": normalized_type,
                "radius_metres": safe_radius,
            }
        )
    except httpx.RequestError as exc:
        return json.dumps(
            {
                "error": f"Network error calling Overpass API: {exc.__class__.__name__}.",
                "amenity_type": normalized_type,
                "radius_metres": safe_radius,
            }
        )
    except json.JSONDecodeError:
        return json.dumps(
            {
                "error": "Overpass API returned invalid JSON.",
                "amenity_type": normalized_type,
                "radius_metres": safe_radius,
            }
        )
    except ValueError:
        return json.dumps(
            {
                "error": "Invalid numeric inputs for coordinates or radius.",
                "amenity_type": normalized_type,
            }
        )

    summary = {
        category: len(items) for category, items in results.items()
    }

    return json.dumps(
        {
            "search_center": {"lat": latitude, "lon": longitude},
            "amenity_type": normalized_type,
            "radius_metres": safe_radius,
            "result_counts": summary,
            "results": results,
        }
    )
