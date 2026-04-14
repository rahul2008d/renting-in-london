from __future__ import annotations

import json
import math
import time

import httpx
from strands import tool


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
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
  node["shop"~"supermarket|convenience|grocery"]["name"~"Indian|Asian|Desi|Patel|Spice|Raj|Punjab|Bangla|Lanka|Halal|World Food|Eastern|Oriental|Exotic|Masala|Namaste|Delhi|Mumbai|Bombay|Karachi|Lahore|Kerala|Tamil|Himalaya",i](around:{radius},{lat},{lon});
  way["shop"~"supermarket|convenience|grocery"]["name"~"Indian|Asian|Desi|Patel|Spice|Raj|Punjab|Bangla|Lanka|Halal|World Food|Eastern|Oriental|Exotic|Masala|Namaste|Delhi|Mumbai|Bombay|Karachi|Lahore|Kerala|Tamil|Himalaya",i](around:{radius},{lat},{lon});
  node["shop"~"supermarket|convenience|grocery"]["cuisine"~"indian|asian|south_asian|bangladeshi|pakistani|sri_lankan",i](around:{radius},{lat},{lon});
);
out center body;
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
  way["shop"="supermarket"](around:{radius},{lat},{lon});
);
out center body;
""".strip()

PARK_QUERY = """
[out:json][timeout:25];
(
  node["leisure"="park"](around:{radius},{lat},{lon});
  way["leisure"="park"](around:{radius},{lat},{lon});
  node["leisure"="garden"](around:{radius},{lat},{lon});
  node["leisure"="nature_reserve"](around:{radius},{lat},{lon});
);
out center body;
""".strip()

GP_SURGERY_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="doctors"](around:{radius},{lat},{lon});
  node["amenity"="clinic"](around:{radius},{lat},{lon});
  node["healthcare"="doctor"](around:{radius},{lat},{lon});
);
out body;
""".strip()

PHARMACY_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="pharmacy"](around:{radius},{lat},{lon});
);
out body;
""".strip()

GYM_QUERY = """
[out:json][timeout:25];
(
  node["leisure"="fitness_centre"](around:{radius},{lat},{lon});
  node["leisure"="sports_centre"](around:{radius},{lat},{lon});
);
out body;
""".strip()

SCHOOL_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="school"](around:{radius},{lat},{lon});
  way["amenity"="school"](around:{radius},{lat},{lon});
);
out center body;
""".strip()

CAFE_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="cafe"](around:{radius},{lat},{lon});
);
out body;
""".strip()

TRANSPORT_QUERY = """
[out:json][timeout:25];
(
  node["railway"="station"](around:{radius},{lat},{lon});
  node["railway"="halt"](around:{radius},{lat},{lon});
  node["station"="subway"](around:{radius},{lat},{lon});
  way["railway"="station"](around:{radius},{lat},{lon});
);
out center body;
""".strip()

POST_OFFICE_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="post_office"](around:{radius},{lat},{lon});
);
out body;
""".strip()

INDIAN_RESTAURANT_QUERY = """
[out:json][timeout:25];
(
  node["amenity"="restaurant"]["cuisine"~"indian|curry|south_asian|bangladeshi|pakistani|sri_lankan",i](around:{radius},{lat},{lon});
);
out body;
""".strip()

QUERY_MAP = {
    "indian_grocery": INDIAN_GROCERY_QUERY,
    "restaurant": RESTAURANT_QUERY,
    "fish_shop": FISH_SHOP_QUERY,
    "supermarket": SUPERMARKET_QUERY,
    "park": PARK_QUERY,
    "gp_surgery": GP_SURGERY_QUERY,
    "pharmacy": PHARMACY_QUERY,
    "gym": GYM_QUERY,
    "school": SCHOOL_QUERY,
    "cafe": CAFE_QUERY,
    "transport": TRANSPORT_QUERY,
    "post_office": POST_OFFICE_QUERY,
    "indian_restaurant": INDIAN_RESTAURANT_QUERY,
}

CATEGORY_GROUPS: dict[str, list[str]] = {
    "essentials": ["supermarket", "pharmacy", "gp_surgery", "park", "transport"],
    "food": ["restaurant", "indian_restaurant", "indian_grocery", "fish_shop", "cafe"],
    "lifestyle": ["gym", "cafe", "park"],
    "family": ["school", "park", "gp_surgery", "pharmacy"],
    "property_check": [
        "supermarket",
        "indian_grocery",
        "indian_restaurant",
        "park",
        "gp_surgery",
        "pharmacy",
        "transport",
    ],
    "all": list(QUERY_MAP.keys()),
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
        # Ways and relations (returned by `nwr` queries with `out center`) lack
        # direct lat/lon; fall back to the centroid provided by Overpass.
        if not isinstance(element_lat, (int, float)) or not isinstance(
            element_lon, (int, float)
        ):
            center = element.get("center") if isinstance(element.get("center"), dict) else {}
            element_lat = center.get("lat")
            element_lon = center.get("lon")
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

    for endpoint in OVERPASS_ENDPOINTS:
        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            if attempt > 0:
                time.sleep(3.0 * attempt)
            try:
                response = client.post(endpoint, data={"data": query})
                if response.status_code in (429, 503, 504):
                    last_exc = httpx.HTTPStatusError(
                        f"Overpass returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                payload = response.json()
                elements = payload.get("elements") if isinstance(payload, dict) else None
                if not isinstance(elements, list):
                    return []
                return _parse_elements(elements, latitude, longitude)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
            except httpx.RequestError as exc:
                last_exc = exc
        # All retries on this endpoint failed, try next
        continue

    if last_exc is not None:
        raise last_exc
    return []


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
        amenity_type: A single category name, a group name, or "all".
            Individual categories: indian_grocery, restaurant, fish_shop,
            supermarket, park, gp_surgery, pharmacy, gym, school, cafe,
            transport, post_office, indian_restaurant.
            Groups: essentials (supermarket, pharmacy, gp_surgery, park,
            transport), food (restaurant, indian_restaurant, indian_grocery,
            fish_shop, cafe), lifestyle (gym, cafe, park), family (school,
            park, gp_surgery, pharmacy), all.
        radius_metres: Search radius in metres (clamped to 100–5000).

    Returns:
        JSON string containing categorized, distance-sorted amenity results.
        On error, returns JSON with an "error" key.
    """
    normalized_type = (amenity_type or "all").strip().lower()
    if normalized_type not in QUERY_MAP and normalized_type not in CATEGORY_GROUPS:
        return json.dumps(
            {
                "error": (
                    "Invalid amenity_type. Use a category (indian_grocery, restaurant, "
                    "fish_shop, supermarket, park, gp_surgery, pharmacy, gym, school, "
                    "cafe, transport, post_office, indian_restaurant), a group "
                    "(essentials, food, lifestyle, family), or 'all'."
                )
            }
        )

    safe_radius = max(100, min(int(radius_metres), 5000))

    if normalized_type in CATEGORY_GROUPS:
        raw_list = CATEGORY_GROUPS[normalized_type]
    else:
        raw_list = [normalized_type]

    seen: set[str] = set()
    categories: list[str] = []
    for cat in raw_list:
        if cat not in seen:
            seen.add(cat)
            categories.append(cat)

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
                    time.sleep(2.0)

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


def format_amenity_summary(results: dict[str, list[dict]]) -> str:
    """Format amenity results into a human-readable one-line summary."""
    parts: list[str] = []
    for category, items in results.items():
        if not items:
            continue
        label = category.replace("_", " ").title()
        nearest = items[0] if items else None
        nearest_info = ""
        if nearest and nearest.get("name") != "Unnamed":
            nearest_info = f" (nearest: {nearest['name']}, {nearest['distance_m']:.0f}m)"
        elif nearest:
            nearest_info = f" (nearest: {nearest['distance_m']:.0f}m)"
        parts.append(f"{len(items)} {label}{nearest_info}")
    return "; ".join(parts) if parts else "No amenities found in range"
