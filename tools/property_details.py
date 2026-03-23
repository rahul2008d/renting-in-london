from __future__ import annotations

import json
import random
import time

import httpx
from strands import tool


RIGHTMOVE_PROPERTY_BASE_URL = "https://www.rightmove.co.uk/properties"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.rightmove.co.uk/property-to-rent/find.html",
}


def _extract_json_blob_from_page_model(html: str) -> str | None:
    marker = "window.PAGE_MODEL = "
    start_marker = html.find(marker)
    if start_marker == -1:
        return None

    json_start = html.find("{", start_marker)
    if json_start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(json_start, len(html)):
        char = html[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return html[json_start : index + 1]

    return None


def _dig(data: dict, *path: str):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_local_number(property_data: dict) -> str | None:
    phone_data = _dig(property_data, "contactInfo", "telephoneNumbers")
    if isinstance(phone_data, dict):
        local_number = phone_data.get("localNumber")
        return local_number if isinstance(local_number, str) else None

    if isinstance(phone_data, list):
        for phone in phone_data:
            if isinstance(phone, dict) and isinstance(phone.get("localNumber"), str):
                return phone["localNumber"]
    return None


def _extract_nearest_stations(property_data: dict) -> list[dict]:
    stations = property_data.get("nearestStations")
    if not isinstance(stations, list):
        return []

    results: list[dict] = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        name = station.get("name")
        if not isinstance(name, str):
            continue
        distance = station.get("distance")
        if distance is None:
            distance = station.get("distanceInMiles")
        results.append({"name": name, "distance": distance})
    return results


def _extract_image_count(property_data: dict) -> int:
    images = property_data.get("images")
    if isinstance(images, list):
        return len(images)

    property_images = property_data.get("propertyImages")
    if isinstance(property_images, dict) and isinstance(property_images.get("images"), list):
        return len(property_images["images"])

    return 0


def _build_informative_summary(result: dict) -> str:
    headline_parts: list[str] = []

    if isinstance(result.get("price"), str) and result.get("price"):
        headline_parts.append(str(result["price"]))
    if isinstance(result.get("bedrooms"), (int, float)):
        headline_parts.append(f"{int(result['bedrooms'])} bed")
    if isinstance(result.get("bathrooms"), (int, float)):
        headline_parts.append(f"{int(result['bathrooms'])} bath")
    if isinstance(result.get("property_type"), str) and result.get("property_type"):
        headline_parts.append(str(result["property_type"]))

    station_text = ""
    stations = result.get("nearest_stations")
    if isinstance(stations, list) and stations:
        first_station = stations[0] if isinstance(stations[0], dict) else None
        if isinstance(first_station, dict):
            name = first_station.get("name")
            distance = first_station.get("distance")
            if isinstance(name, str):
                station_text = f"Nearest station: {name}"
                if isinstance(distance, (int, float, str)):
                    station_text += f" ({distance} miles)"

    feature_text = ""
    features = result.get("key_features")
    if isinstance(features, list) and features:
        feature_text = ", ".join(str(item) for item in features[:4] if isinstance(item, str))

    lines: list[str] = []
    if headline_parts:
        lines.append(" | ".join(headline_parts))
    if station_text:
        lines.append(station_text)
    if feature_text:
        lines.append(f"Top features: {feature_text}")
    if isinstance(result.get("lettings"), dict):
        furnish = result["lettings"].get("furnish_type")
        minimum_term = result["lettings"].get("minimum_term")
        if furnish or minimum_term:
            lines.append(f"Lettings: furnish={furnish or 'n/a'}, minimum_term={minimum_term or 'n/a'}")

    return "\n".join(lines)


@tool
def get_property_details(property_id: str) -> str:
    """Get full details for a single Rightmove rental property.

    Args:
        property_id: Rightmove property identifier used in the property URL.

    Returns:
        JSON string containing detailed structured property data, or an error payload.
        Success payload fields include address, pricing, type, bedrooms, bathrooms,
        description, key features, lettings info, agent contact details, location,
        nearest stations, EPC rating, and image count.
    """
    if not property_id or not property_id.strip():
        return json.dumps({"error": "property_id is required."})

    cleaned_property_id = property_id.strip()
    url = f"{RIGHTMOVE_PROPERTY_BASE_URL}/{cleaned_property_id}"

    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            # Brief jitter to avoid rapid-fire calls when the agent fetches multiple properties
            time.sleep(random.uniform(0.5, 1.5))

            response = None
            last_exc: Exception | None = None
            for attempt in range(3):
                if attempt > 0:
                    time.sleep(2 ** attempt)
                try:
                    response = client.get(url)
                    if response.status_code == 429:
                        return json.dumps(
                            {
                                "error": "Rightmove rate-limited the request (429). Please retry shortly.",
                                "property_id": cleaned_property_id,
                                "url": url,
                            }
                        )
                    if response.status_code == 404:
                        return json.dumps(
                            {
                                "error": f"Property {cleaned_property_id} not found on Rightmove.",
                                "property_id": cleaned_property_id,
                                "url": url,
                            }
                        )
                    response.raise_for_status()
                    last_exc = None
                    break
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                except httpx.RequestError as exc:
                    last_exc = exc

            if last_exc is not None:
                raise last_exc

    except httpx.TimeoutException:
        return json.dumps(
            {
                "error": "Request to Rightmove property page timed out.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {
                "error": f"Rightmove property page returned HTTP {exc.response.status_code}.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )
    except httpx.RequestError as exc:
        return json.dumps(
            {
                "error": f"Network error fetching property page: {exc.__class__.__name__}.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )

    json_blob = _extract_json_blob_from_page_model(response.text)
    if not json_blob:
        return json.dumps(
            {
                "error": "PAGE_MODEL was not found in the property page.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )

    try:
        page_model = json.loads(json_blob)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "error": "Failed to parse PAGE_MODEL JSON from property page.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )

    property_data = page_model.get("propertyData") if isinstance(page_model, dict) else None
    if not isinstance(property_data, dict):
        return json.dumps(
            {
                "error": "propertyData was not found in PAGE_MODEL.",
                "property_id": cleaned_property_id,
                "url": url,
            }
        )

    result = {
        "property_id": cleaned_property_id,
        "url": url,
        "address": _dig(property_data, "address", "displayAddress"),
        "price": _dig(property_data, "prices", "primaryPrice"),
        "property_type": property_data.get("propertySubType"),
        "bedrooms": property_data.get("bedrooms"),
        "bathrooms": property_data.get("bathrooms"),
        "description": _dig(property_data, "text", "description"),
        "key_features": property_data.get("keyFeatures") if isinstance(property_data.get("keyFeatures"), list) else [],
        "lettings": {
            "let_available_date": _dig(property_data, "lettings", "letAvailableDate"),
            "furnish_type": _dig(property_data, "lettings", "furnishType"),
            "deposit": _dig(property_data, "lettings", "deposit"),
            "minimum_term": _dig(property_data, "lettings", "minimumTermOfTenancyDescription"),
        },
        "customer_name": property_data.get("customerName"),
        "branch_name": property_data.get("branchName"),
        "contact_number": _extract_local_number(property_data),
        "location": {
            "latitude": _dig(property_data, "location", "latitude"),
            "longitude": _dig(property_data, "location", "longitude"),
        },
        "nearest_stations": _extract_nearest_stations(property_data),
        "epc_rating": _dig(property_data, "epc", "currentEnergyRating"),
        "image_count": _extract_image_count(property_data),
    }
    result["informative_summary"] = _build_informative_summary(result)

    return json.dumps(result)
