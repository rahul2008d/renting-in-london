from __future__ import annotations

import json
import math
import random
import re
import time
import httpx
from strands import tool

from data.london_areas import (
    get_location_id,
    get_london_borough_areas,
    get_zone_from_address,
)
from tools.listing_signals import extract_all_signals
from tools.price_scorer import (
    WEIGHT_PRESETS,
    _amenity_score,
    _amenity_tag_score,
    _commute_score,
    _data_completeness_score,
    _freshness_score,
    _location_score,
    _normalize_key_features,
    _parking_score,
    _price_score,
    _resolve_area_name,
    _space_score,
    _to_float as _score_to_float,
    _to_int as _score_to_int,
    recommendation_tier,
)


RIGHTMOVE_SEARCH_API = "https://www.rightmove.co.uk/api/_search"
RIGHTMOVE_REFERER = "https://www.rightmove.co.uk/property-to-rent/find.html"
RIGHTMOVE_TYPEAHEAD_BASE = "https://www.rightmove.co.uk/typeAhead/uknostreet"

MANDATORY_MAX_PRICE = 1900
MANDATORY_MIN_BEDROOMS = 2
MANDATORY_MIN_BATHROOMS = 2
MANDATORY_MAX_DISTANCE_MILES = 5.0
# Soft expansion for "With Trade-offs" tier when strict filtering returns few results
SOFT_MAX_PRICE = 2300
SOFT_MAX_DISTANCE_MILES = 7.0
PAGE_SIZE = 24
MAX_LOCATION_CANDIDATES = 4
MAX_PAGES_PER_LOCATION = 42
LONDON_POSTCODE_PREFIX = re.compile(r"\b(?:E|EC|N|NW|SE|SW|W|WC)\d", re.IGNORECASE)
POSTCODE_LIKE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*\d[A-Z]{2}\b", re.IGNORECASE)
OUTWARD_POSTCODE_TOKEN = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b", re.IGNORECASE)

# Floor area unit regexes used by _extract_floor_area_sqft
_FLOOR_SQFT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*ft\b|sqft\b|ft2\b|ft\u00b2)",
    re.IGNORECASE,
)
_FLOOR_SQM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m(?:etres?)?\b|sqm\b|m2\b|m\u00b2)",
    re.IGNORECASE,
)

LONDON_LAT_MIN = 51.20
LONDON_LAT_MAX = 51.75
LONDON_LON_MIN = -0.55
LONDON_LON_MAX = 0.35

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": RIGHTMOVE_REFERER,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

SORT_MAP = {
    "newest": 6,
    "lowest_price": 1,
    "highest_price": 2,
}

PROPERTY_TYPE_MAP = {
    "flat": "flat",
    "house": "house",
    "studio": "studio",
}

FURNISHED_MAP = {
    "furnished": "furnished",
    "unfurnished": "unfurnished",
}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokenize_for_typeahead(area: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", area or "").upper()
    if not cleaned:
        return ""
    tokens = [cleaned[index : index + 2] for index in range(0, len(cleaned), 2)]
    return "/".join(tokens)


def _extract_location_identifier_from_item(item: dict) -> str | None:
    for key in ("locationIdentifier", "value", "id"):
        value = item.get(key)
        if isinstance(value, str) and re.match(r"^(REGION|OUTCODE|POSTCODE|STATION)\^", value):
            return value

    for key in ("url", "searchUrl", "location"):
        value = item.get(key)
        if isinstance(value, str):
            match = re.search(r"(REGION\^\d+|OUTCODE\^\d+|POSTCODE\^[^&]+|STATION\^\d+)", value)
            if match:
                return match.group(1)

    return None


def _extract_typeahead_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("typeAheadLocations", "items", "locations", "suggestions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _resolve_location_identifiers(client: httpx.Client, area: str) -> list[str]:
    queries = [area, f"{area} london", f"london {area}"]
    normalized_area = (area or "").strip().lower()
    resolved: list[str] = []
    seen: set[str] = set()

    for query in queries:
        tokenized = _tokenize_for_typeahead(query)
        if not tokenized:
            continue

        typeahead_url = f"{RIGHTMOVE_TYPEAHEAD_BASE}/{tokenized}/"
        response = client.get(typeahead_url)
        response.raise_for_status()

        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None

        items = _extract_typeahead_items(payload)

        london_hits: list[dict] = []
        area_hits: list[dict] = []
        for item in items:
            display_name = str(item.get("displayName") or item.get("label") or "").lower()
            if "london" in display_name:
                london_hits.append(item)
            if normalized_area and normalized_area in display_name:
                area_hits.append(item)

        for bucket in (london_hits, area_hits, items):
            for item in bucket:
                location_identifier = _extract_location_identifier_from_item(item)
                if location_identifier and location_identifier not in seen:
                    seen.add(location_identifier)
                    resolved.append(location_identifier)
                    if len(resolved) >= MAX_LOCATION_CANDIDATES:
                        return resolved

    static_location_id = get_location_id(area)
    if static_location_id and static_location_id not in seen:
        resolved.append(static_location_id)

    return resolved[:MAX_LOCATION_CANDIDATES]


def _extract_properties_from_next_data_html(html: str) -> tuple[list[dict] | None, int | None]:
    next_data = _extract_next_data_json(html)
    if not isinstance(next_data, dict):
        return None, None

    search_results = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("searchResults", {})
    )

    properties = search_results.get("properties")
    if not isinstance(properties, list):
        return None, _safe_int(search_results.get("resultCount"), 0)

    parsed = [prop for prop in properties if isinstance(prop, dict)]
    return parsed, _safe_int(search_results.get("resultCount"), len(parsed))


def _extract_property(prop: dict) -> dict:
    property_id = prop.get("id")
    price = prop.get("price") or {}
    location = prop.get("location") or {}
    property_images = (prop.get("propertyImages") or {}).get("images") or []
    text_blob = _collect_text_fields(prop)
    parking_signal = _has_parking(text_blob)
    if _has_no_parking(text_blob):
        parking_status = "excluded"
    elif parking_signal:
        parking_status = "confirmed"
    else:
        parking_status = "unconfirmed"
    furnished_signal = _is_furnished(text_blob)
    excluded_type_signal = _is_excluded_type(prop, text_blob)
    amenity_tags = _extract_amenity_tags(text_blob)
    floor_area_sqft = _extract_floor_area_sqft(
        text_blob,
        prop.get("displaySize") if isinstance(prop.get("displaySize"), str) else None,
    )
    display_address = prop.get("displayAddress") or ""

    price_amount = _safe_int(price.get("amount"), 0)
    bedrooms = _safe_int(prop.get("bedrooms"), 0)
    bathrooms = _safe_int(prop.get("bathrooms"), 0)
    distance_miles = _to_float(prop.get("distance"))

    mandatory_checks = {
        "price_ok": price_amount > 0 and price_amount <= MANDATORY_MAX_PRICE,
        "bedrooms_ok": bedrooms >= MANDATORY_MIN_BEDROOMS,
        "bathrooms_ok": bathrooms >= MANDATORY_MIN_BATHROOMS,
        "distance_ok": distance_miles is None or distance_miles <= MANDATORY_MAX_DISTANCE_MILES,
        "parking_ok": parking_signal,
        "furnished_ok": furnished_signal,
        "excluded_type_ok": not excluded_type_signal,
    }

    match_summary: list[str] = []
    if mandatory_checks["price_ok"]:
        match_summary.append(f"Within budget (<= GBP {MANDATORY_MAX_PRICE} pcm)")
    if mandatory_checks["bedrooms_ok"] and mandatory_checks["bathrooms_ok"]:
        match_summary.append("Meets 2-bed/2-bath minimum")
    if mandatory_checks["parking_ok"]:
        match_summary.append("Parking signal detected")
    if mandatory_checks["furnished_ok"]:
        match_summary.append("Furnished signal detected")
    if mandatory_checks["distance_ok"]:
        match_summary.append("Within 5-mile radius filter")

    zone = get_zone_from_address(display_address)

    return {
        "id": property_id,
        "price_pcm": price.get("amount"),
        "price_display": _extract_price_display(price),
        "bedrooms": prop.get("bedrooms"),
        "bathrooms": prop.get("bathrooms"),
        "address": display_address,
        "zone": zone,
        "property_type": prop.get("propertySubType"),
        "property_type_full": prop.get("propertyTypeFullDescription"),
        "display_size": prop.get("displaySize"),
        "display_status": prop.get("displayStatus"),
        "students": prop.get("students"),
        "distance_miles": distance_miles,
        "formatted_distance": prop.get("formattedDistance"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "agent": prop.get("customerName"),
        "branch": prop.get("formattedBranchName"),
        "first_visible_date": prop.get("firstVisibleDate"),
        "listing_update": _extract_listing_update(prop),
        "let_available_date": prop.get("letAvailableDate"),
        "key_features": _extract_key_features(prop),
        "mandatory_checks": mandatory_checks,
        "match_summary": match_summary,
        "url": f"https://www.rightmove.co.uk/properties/{property_id}" if property_id else None,
        "images": [
            img.get("srcUrl")
            for img in property_images[:3]
            if isinstance(img, dict) and img.get("srcUrl")
        ],
        "parking_status": parking_status,
        "summary": prop.get("summary"),
        "amenity_tags": amenity_tags,
        "floor_area_sqft": floor_area_sqft,
    }


def _extract_price_display(price: dict) -> str | None:
    display_prices = price.get("displayPrices")
    if isinstance(display_prices, list):
        for item in display_prices:
            if isinstance(item, dict):
                display_price = item.get("displayPrice")
                if isinstance(display_price, str) and display_price.strip():
                    return display_price
    fallback_display = price.get("displayAmount")
    if isinstance(fallback_display, str) and fallback_display.strip():
        return fallback_display
    return None


def _extract_listing_update(prop: dict) -> dict:
    update = prop.get("listingUpdate")
    if not isinstance(update, dict):
        return {}
    return {
        "reason": update.get("listingUpdateReason"),
        "date": update.get("listingUpdateDate"),
        "is_recent": bool(prop.get("isRecent")),
    }


def _extract_key_features(prop: dict) -> list[str]:
    features = prop.get("keyFeatures")
    if not isinstance(features, list):
        return []

    parsed: list[str] = []
    for feature in features:
        if isinstance(feature, dict):
            description = feature.get("description")
            if isinstance(description, str) and description.strip():
                parsed.append(description.strip())
        elif isinstance(feature, str) and feature.strip():
            parsed.append(feature.strip())

    return parsed[:8]


def _extract_next_data_json(html: str) -> dict | None:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _fetch_properties_from_search_page(
    client: httpx.Client,
    params: dict[str, object],
) -> tuple[list[dict] | None, int | None]:
    # Pass all non-None params so that find.html returns the correct resultCount
    # (with server-side filters active, resultCount reflects the true filtered total
    # rather than just the current-page count, which is critical for pagination).
    full_params = {k: v for k, v in params.items() if v is not None}
    response = client.get(RIGHTMOVE_REFERER, params=full_params)
    response.raise_for_status()
    return _extract_properties_from_next_data_html(response.text)


def _collect_text_fields(prop: dict) -> str:
    pieces: list[str] = []

    for key in ("propertySubType", "propertyTypeFullDescription", "summary", "displayStatus"):
        value = prop.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value)

    key_features = prop.get("keyFeatures")
    if isinstance(key_features, list):
        for feature in key_features:
            if isinstance(feature, dict):
                description = feature.get("description")
                if isinstance(description, str) and description.strip():
                    pieces.append(description)
            elif isinstance(feature, str) and feature.strip():
                pieces.append(feature)

    keywords = prop.get("keywords")
    if isinstance(keywords, list):
        for keyword in keywords:
            if isinstance(keyword, str) and keyword.strip():
                pieces.append(keyword)

    return " ".join(pieces).lower()


def _is_london_listing(prop: dict) -> bool:
    address = prop.get("displayAddress")
    if not isinstance(address, str) or not address.strip():
        return True

    lowered = address.lower()
    if " london" in lowered:
        return True

    if LONDON_POSTCODE_PREFIX.search(address):
        return True

    postcode_match = POSTCODE_LIKE.search(address)
    if postcode_match:
        outward = (postcode_match.group(1) or "").upper()
        if not re.match(r"^(E|EC|N|NW|SE|SW|W|WC)", outward):
            return False

    outward_matches = OUTWARD_POSTCODE_TOKEN.findall(address.upper())
    for outward in outward_matches:
        if re.match(r"^(E|EC|N|NW|SE|SW|W|WC)\d", outward):
            return True
        if re.match(r"^[A-Z]{1,2}\d", outward) and not re.match(r"^(E|EC|N|NW|SE|SW|W|WC)", outward):
            return False

    return True


def _is_in_london_bounds(prop: dict) -> bool:
    location = prop.get("location") if isinstance(prop.get("location"), dict) else {}
    latitude = _to_float(location.get("latitude"))
    longitude = _to_float(location.get("longitude"))

    if latitude is None or longitude is None:
        return True

    return (
        LONDON_LAT_MIN <= latitude <= LONDON_LAT_MAX
        and LONDON_LON_MIN <= longitude <= LONDON_LON_MAX
    )


def _passes_london_check(prop: dict) -> bool:
    """Return True if the property is in Greater London.

    GPS coordinates are used as the authoritative check when available — this
    correctly handles outer-London boroughs whose postcode areas (HA, UB, EN,
    RM, IG, DA, BR, CR, SM, KT, TW …) are not covered by the traditional
    E/EC/N/NW/SE/SW/W/WC prefix list used by _is_london_listing().
    Falls back to the text/postcode heuristic only when coordinates are absent.
    """
    location = prop.get("location") if isinstance(prop.get("location"), dict) else {}
    lat = _to_float(location.get("latitude"))
    lon = _to_float(location.get("longitude"))
    if lat is not None and lon is not None:
        return (
            LONDON_LAT_MIN <= lat <= LONDON_LAT_MAX
            and LONDON_LON_MIN <= lon <= LONDON_LON_MAX
        )
    return _is_london_listing(prop)


_NO_PARKING_PHRASES: tuple[str, ...] = (
    "no parking",
    "no off-street parking",
    "no off street parking",
    "no allocated parking",
    "no private parking",
    "no resident parking",
    "no residents parking",
    "no on-site parking",
    "no onsite parking",
    "no garage",
    "no driveway",
    "parking not available",
    "parking not included",
    "does not include parking",
    "does not come with parking",
    "without parking",
    "excludes parking",
)


def _has_no_parking(text_blob: str) -> bool:
    """True when listing text explicitly negates parking (checked before positive signals)."""
    return any(phrase in text_blob for phrase in _NO_PARKING_PHRASES)


def _has_parking(text_blob: str) -> bool:
    if _has_no_parking(text_blob):
        return False
    parking_terms = [
        "parking",
        "garage",
        "car park",
        "driveway",
        "off street",
        "off-street",
        "car port",
        "carport",
        "allocated parking",
        "allocated space",
        "parking permit",
        "residents permit",
        "car space",
        "private parking",
        "resident parking",
        "residents parking",
        "on-site parking",
        "onsite parking",
        "visitor parking",
    ]
    return any(term in text_blob for term in parking_terms)


def _is_furnished(text_blob: str) -> bool:
    # Server-side filter uses furnished,partFurnished. Client-side hard-reject fires
    # only when the listing text explicitly says "unfurnished".
    # Guard against "furnished or unfurnished" / "furnished / unfurnished" phrasing
    # where some agents offer both options — that should not be treated as unfurnished.
    return not re.search(r"(?<!or\s)(?<!/\s)unfurnished", text_blob)


def _is_excluded_type(prop: dict, text_blob: str) -> bool:
    if bool(prop.get("students")):
        return True

    excluded_terms = [
        "house share",
        "house-share",
        "retirement",
        "student accommodation",
        "student accomodation",
        "student let",
    ]
    return any(term in text_blob for term in excluded_terms)


def _extract_amenity_tags(text_blob: str) -> list[str]:
    """Scan listing text and return a deduplicated list of nice-to-have feature tags."""
    tags: list[str] = []

    if "dishwasher" in text_blob:
        tags.append("Dishwasher")

    if any(term in text_blob for term in ("washer-dryer", "washer dryer", "washing machine")):
        tags.append("Washer/Dryer")

    if any(term in text_blob for term in ("balcony", "terrace", "roof terrace", "juliet balcony")):
        tags.append("Balcony/Terrace")

    if any(term in text_blob for term in ("en-suite", "en suite", "ensuite")):
        tags.append("En-suite")

    if any(term in text_blob for term in ("bills included", "bills inc")):
        tags.append("Bills Included")

    if any(term in text_blob for term in ("pet friendly", "pet-friendly", "pets allowed", "pets considered")):
        tags.append("Pet Friendly")

    # Match "garden" but exclude "garden square" and "garden view" (ornamental references)
    garden_match = re.search(r"\bgarden\b", text_blob)
    if garden_match:
        following = text_blob[garden_match.end() : garden_match.end() + 8]
        if not following.startswith(" square") and not following.startswith(" view"):
            tags.append("Garden")

    if any(term in text_blob for term in ("gym", "fitness", "concierge", "porter")):
        tags.append("Building Amenities")

    if any(
        term in text_blob
        for term in ("newly built", "new build", "newly renovated", "recently refurbished", "recently renovated")
    ):
        tags.append("Newly Refurbished")

    if any(term in text_blob for term in ("lift", "elevator")):
        tags.append("Lift")

    if any(term in text_blob for term in ("bike storage", "bicycle storage", "cycle storage")):
        tags.append("Bike Storage")

    return tags


def _extract_floor_area_sqft(text_blob: str, display_size: str | None = None) -> int | None:
    """Parse floor area from listing text or displaySize. Returns sqft integer, or None."""

    def _parse(text: str) -> int | None:
        m = _FLOOR_SQFT_RE.search(text)
        if m:
            return round(float(m.group(1)))
        m = _FLOOR_SQM_RE.search(text)
        if m:
            return round(float(m.group(1)) * 10.764)
        return None

    result = _parse(text_blob)
    if result is not None:
        return result
    if display_size:
        return _parse(display_size)
    return None


def _mandatory_reject_reasons(prop: dict) -> list[str]:
    reasons: list[str] = []

    price_amount = _safe_int((prop.get("price") or {}).get("amount"), 0)
    if price_amount <= 0 or price_amount > MANDATORY_MAX_PRICE:
        reasons.append("price_over_budget")

    bedrooms = _safe_int(prop.get("bedrooms"), 0)
    if bedrooms < MANDATORY_MIN_BEDROOMS:
        reasons.append("bedrooms_below_min")

    bathrooms = _safe_int(prop.get("bathrooms"), 0)
    if bathrooms < MANDATORY_MIN_BATHROOMS:
        reasons.append("bathrooms_below_min")

    distance = _to_float(prop.get("distance"))
    if distance is not None and distance > MANDATORY_MAX_DISTANCE_MILES:
        reasons.append("distance_over_limit")

    text_blob = _collect_text_fields(prop)
    if _is_excluded_type(prop, text_blob):
        reasons.append("excluded_listing_type")
    if not _is_furnished(text_blob):
        reasons.append("furnished_not_detected")
    # Note: parking is intentionally NOT a mandatory reject reason — the search API
    # only returns a short summary, not the full description where parking is typically
    # mentioned. Parking is handled as a soft annotation pass in _run_search.

    return reasons


def _passes_soft_filters(prop: dict) -> bool:
    """Check if property qualifies for 'With Trade-offs' tier (single minor deviation allowed)."""
    price_amount = _safe_int((prop.get("price") or {}).get("amount"), 0)
    bedrooms = _safe_int(prop.get("bedrooms"), 0)
    bathrooms = _safe_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance"))
    text_blob = _collect_text_fields(prop)

    if bedrooms < MANDATORY_MIN_BEDROOMS:
        return False
    if _is_excluded_type(prop, text_blob):
        return False
    if not _is_furnished(text_blob):
        return False

    if price_amount <= 0 or price_amount > SOFT_MAX_PRICE:
        return False
    if distance is not None and distance > SOFT_MAX_DISTANCE_MILES:
        return False
    if bathrooms < 1:
        return False

    reasons = _mandatory_reject_reasons(prop)
    if not reasons:
        return True

    soft_reasons = {"price_over_budget", "distance_over_limit", "bathrooms_below_min"}
    failed_soft = [r for r in reasons if r in soft_reasons]
    if len(failed_soft) != 1:
        return False

    reason = failed_soft[0]
    if reason == "price_over_budget":
        return MANDATORY_MAX_PRICE < price_amount <= SOFT_MAX_PRICE
    if reason == "distance_over_limit":
        return MANDATORY_MAX_DISTANCE_MILES < (distance or 0) <= SOFT_MAX_DISTANCE_MILES
    if reason == "bathrooms_below_min":
        return bathrooms == 1

    return False


def _get_soft_trade_off_reasons(prop: dict) -> list[str]:
    """Return human-readable trade-off reasons for soft-tier properties."""
    reasons: list[str] = []
    price_amount = _safe_int((prop.get("price") or {}).get("amount"), 0)
    bathrooms = _safe_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance"))
    text_blob = _collect_text_fields(prop)

    if price_amount > MANDATORY_MAX_PRICE:
        reasons.append(f"Slightly over budget (£{price_amount} pcm vs £{MANDATORY_MAX_PRICE} max)")
    if bathrooms < MANDATORY_MIN_BATHROOMS:
        reasons.append(f"Fewer bathrooms ({bathrooms} vs {MANDATORY_MIN_BATHROOMS} min)")
    if distance is not None and distance > MANDATORY_MAX_DISTANCE_MILES:
        reasons.append(f"Slightly further ({distance:.1f} miles vs {MANDATORY_MAX_DISTANCE_MILES} max)")
    if _has_no_parking(text_blob):
        reasons.append("Listing explicitly states no parking")
    elif not _has_parking(text_blob):
        reasons.append("Parking not explicitly mentioned in listing — verify with agent")

    return reasons


def _compute_property_score(prop: dict) -> float:
    """Score property for ranking (0-100). Higher = better match."""
    price = _safe_int((prop.get("price") or {}).get("amount"), 0)
    bedrooms = _safe_int(prop.get("bedrooms"), 0)
    bathrooms = _safe_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance"))

    if price <= 0:
        return 0.0

    price_score = max(0.0, min(35.0, ((MANDATORY_MAX_PRICE - price) / MANDATORY_MAX_PRICE) * 35.0))
    if price > MANDATORY_MAX_PRICE:
        price_score = max(0.0, 20.0 - ((price - MANDATORY_MAX_PRICE) / 200.0) * 10.0)

    space_score = min(30.0, max(0.0, bedrooms * 8.0 + bathrooms * 7.0))
    distance_score = 20.0 if distance is None else max(0.0, 20.0 - (distance * 3.0))

    features = prop.get("keyFeatures") or []
    info_score = min(15.0, len(features) * 1.25) if isinstance(features, list) else 0.0

    return round(price_score + space_score + distance_score + info_score, 2)


def _fetch_raw_properties_for_location(
    client: httpx.Client,
    params: dict[str, object],
    location_identifier: str,
    max_pages: int = 2,
) -> tuple[list[dict], int]:
    """Fetch raw properties from Rightmove for a single location. Returns (properties, result_count)."""
    raw: list[dict] = []
    result_count = 0
    params = dict(params)
    params["locationIdentifier"] = location_identifier

    # Set radius=0.0 for REGION searches; keep caller-supplied radius for OUTCODE/POSTCODE.
    if location_identifier.startswith("REGION^"):
        params["radius"] = 0.0

    pages_to_fetch = max_pages  # Recalculated after first page using resultCount

    page_index = 0
    while page_index < pages_to_fetch:
        page_params = dict(params)
        page_params["index"] = page_index * PAGE_SIZE

        # Retry logic: 3 attempts with exponential backoff (2s, 4s)
        response = None
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt > 0:
                time.sleep(2 ** attempt)
            try:
                response = client.get(RIGHTMOVE_SEARCH_API, params=page_params)
                if response.status_code == 429:
                    response.raise_for_status()
                response.raise_for_status()
                last_exc = None
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429:
                    break  # Don't retry rate-limit errors
            except httpx.RequestError as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc

        assert response is not None

        page_props: list[dict] | None = None
        page_result_count = 0
        content_type = (response.headers.get("content-type") or "").lower()
        # API often returns HTML error page; prefer find.html when JSON not returned
        if "application/json" in content_type and "text/html" not in content_type:
            try:
                data = response.json()
                api_props = data.get("properties") if isinstance(data, dict) else None
                if isinstance(api_props, list):
                    page_props = [p for p in api_props if isinstance(p, dict)]
                    page_result_count = _safe_int(data.get("resultCount"), len(page_props))
            except json.JSONDecodeError:
                pass
        if not page_props:
            # API returned HTML or empty; try find.html (works when API fails)
            page_props, page_result_count = _extract_properties_from_next_data_html(response.text)
            if not page_props:
                page_props, page_result_count = _fetch_properties_from_search_page(client, page_params)

        # Update result_count and recalculate total pages needed from first page's resultCount
        if page_result_count and page_result_count > result_count:
            result_count = page_result_count
            pages_to_fetch = min(max_pages, math.ceil(result_count / PAGE_SIZE))

        if isinstance(page_props, list):
            for prop in page_props:
                if _passes_london_check(prop):
                    raw.append(prop)

        if not page_props:
            break

        # Sleep between page fetches (skip after the last page)
        if page_index < pages_to_fetch - 1:
            time.sleep(random.uniform(0.5, 1.5))

        page_index += 1

    return raw, result_count


def _run_search(
    *,
    areas: list[str],
    max_price: int,
    radius_miles: float,
    include_soft_tier: bool = False,
    max_pages_per_location: int = 3,
    max_results: int = 50,
    resolve_via_typeahead: bool = False,
    sort_by: str = "newest",
    property_type: str = "",
    furnished: str = "",
    min_bedrooms: int = MANDATORY_MIN_BEDROOMS,
    max_bedrooms: int = 4,
) -> tuple[
    list[dict],
    list[dict],
    list[dict],
    list[list[str]],
    list[str],
    dict[str, object],
]:
    """Shared search core. Fetches from Rightmove, filters, returns (raw, strict, soft, reject_reasons, areas_queried, params)."""
    normalized_sort = (sort_by or "newest").strip().lower()
    sort_type = SORT_MAP.get(normalized_sort, SORT_MAP["newest"])

    params: dict[str, object] = {
        "channel": "RENT",
        "maxPrice": max_price,
        "minBedrooms": min_bedrooms,
        "maxBedrooms": max_bedrooms,
        "minBathrooms": MANDATORY_MIN_BATHROOMS,
        "numberOfPropertiesPerPage": PAGE_SIZE,
        "sortType": sort_type,
        "includeLetAgreed": "false",
        "currencyCode": "GBP",
        "areaSizeUnit": "miles",
        "radius": radius_miles,
        # Use furnished,partFurnished to cast the widest net for occupied/furnished
        # properties. Omitting furnishTypes entirely returns ~1 result (Rightmove API
        # does not default to "all" — it returns almost nothing without a filter).
        # furnished,unfurnished also returns ~1 result due to a Rightmove API quirk.
        # furnished,partFurnished returns ~816 results and includes properties where
        # agents left the furnishing dropdown unset (they appear tagged as partFurnished
        # in search results even if blank on the detail page).
        # Client-side _is_furnished() remains the hard reject gate — it only rejects
        # listings that explicitly say "unfurnished" in their text.
        # Note: mustHave=parking is intentionally omitted — it silently drops listings
        # where parking is mentioned only in free text. Client-side _has_parking() handles
        # detection for both the strict tier and the parking_not_detected trade-off tier.
        "furnishTypes": "furnished,partFurnished",
    }
    if (property_type or "").strip().lower() in PROPERTY_TYPE_MAP:
        params["propertyTypes"] = PROPERTY_TYPE_MAP[(property_type or "").strip().lower()]
    # If caller explicitly requests unfurnished, override the default
    if (furnished or "").strip().lower() == "unfurnished":
        params["furnishTypes"] = "unfurnished"
    elif (furnished or "").strip().lower() == "furnished":
        params["furnishTypes"] = "furnished,partFurnished"

    seen_ids: set[str] = set()
    raw_all: list[dict] = []
    areas_queried: list[str] = []
    location_pairs: list[tuple[str, str]] = []

    with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
        for area in areas:
            if not area or not str(area).strip():
                continue
            if resolve_via_typeahead:
                identifiers = _resolve_location_identifiers(client, area)
                for loc_id in identifiers:
                    location_pairs.append((area, loc_id))
            else:
                loc_id = get_location_id(area)
                if loc_id:
                    location_pairs.append((area, loc_id))

        for borough_index, (area_name, loc_id) in enumerate(location_pairs):
            batch, _ = _fetch_raw_properties_for_location(
                client, params, loc_id, max_pages=max_pages_per_location
            )
            if area_name not in areas_queried:
                areas_queried.append(area_name)
            for prop in batch:
                pid = str(prop.get("id") or "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    raw_all.append(prop)
            # Pause between boroughs to avoid rate-limiting (skip after last borough)
            if borough_index < len(location_pairs) - 1:
                time.sleep(5.0)

    strict_list: list[dict] = []
    soft_list: list[dict] = []
    rejected_reasons_by_property: list[list[str]] = []

    for prop in raw_all:
        reasons = _mandatory_reject_reasons(prop)
        if not reasons:
            strict_list.append(prop)
        elif include_soft_tier and _passes_soft_filters(prop):
            soft_list.append(prop)
        else:
            rejected_reasons_by_property.append(reasons)

    strict_list.sort(key=_compute_property_score, reverse=True)
    soft_list.sort(key=_compute_property_score, reverse=True)

    # Parking annotation pass: properties in strict_list without a positive parking signal
    # (unconfirmed or explicit no-parking) move to soft_list. Excluded listings get the
    # trade-off reason "Listing explicitly states no parking" in _get_soft_trade_off_reasons.
    confirmed_strict: list[dict] = []
    for prop in strict_list:
        text_blob = _collect_text_fields(prop)
        if _has_parking(text_blob):
            confirmed_strict.append(prop)
        else:
            # unconfirmed OR explicit no parking (excluded) — same tier as soft
            soft_list.append(prop)
    strict_list = confirmed_strict
    soft_list.sort(key=_compute_property_score, reverse=True)

    return raw_all, strict_list, soft_list, rejected_reasons_by_property, areas_queried, params


def _build_constraint_impact_summary(
    rejected_reasons_by_property: list[list[str]],
) -> dict[str, dict[str, object]]:
    labels = {
        "price_over_budget": "Relax max price",
        "bedrooms_below_min": "Relax minimum bedrooms",
        "bathrooms_below_min": "Relax minimum bathrooms",
        "furnished_not_detected": "Relax furnished requirement",
        "parking_not_detected": "Relax parking requirement",
        "distance_over_limit": "Relax max distance",
        "excluded_listing_type": "Allow excluded listing types",
    }

    impact: dict[str, dict[str, object]] = {}
    for rule_key, label in labels.items():
        newly_eligible = 0
        blocked_by_other_rules = 0
        for reasons in rejected_reasons_by_property:
            if rule_key not in reasons:
                continue
            other_reasons = [reason for reason in reasons if reason != rule_key]
            if other_reasons:
                blocked_by_other_rules += 1
            else:
                newly_eligible += 1

        impact[rule_key] = {
            "label": label,
            "newly_eligible_if_only_this_rule_relaxed": newly_eligible,
            "still_blocked_by_other_rules": blocked_by_other_rules,
        }

    return impact


MAX_TOP_PICKS = 50
MAX_TRADE_OFFS = 50


def _score_extracted_property(
    prop: dict,
    workplace_lat: float = 51.5154,
    workplace_lon: float = -0.0820,
) -> None:
    """Score an already-extracted property dict in-place (balanced weights; matches score_properties)."""
    weights = WEIGHT_PRESETS["balanced"]

    price = _score_to_float(prop.get("price_pcm"), 0.0)
    bedrooms = _score_to_int(prop.get("bedrooms"), 0)
    property_type = str(prop.get("property_type") or "")
    address = str(prop.get("address") or "")
    latitude = _score_to_float(prop.get("latitude"), 0.0)
    longitude = _score_to_float(prop.get("longitude"), 0.0)

    parking_status = str(prop.get("parking_status", "unconfirmed"))
    first_visible_date = prop.get("first_visible_date")
    floor_area_sqft = prop.get("floor_area_sqft")
    floor_sq: int | None = None
    if isinstance(floor_area_sqft, (int, float)) and floor_area_sqft > 0:
        floor_sq = int(floor_area_sqft)

    amenity_tags = prop.get("amenity_tags") if isinstance(prop.get("amenity_tags"), list) else []
    summary_text = str(prop.get("summary") or "")
    key_features_list = _normalize_key_features(prop.get("key_features"))
    epc_raw = prop.get("epc_rating")
    epc_rating = str(epc_raw).strip() if epc_raw is not None and str(epc_raw).strip() else None

    text_pieces = [summary_text] + [str(f) for f in key_features_list] + [
        str(prop.get("property_type") or ""),
        str(prop.get("property_type_full") or ""),
        str(prop.get("display_status") or ""),
    ]
    text_blob = " ".join(text_pieces).lower()

    signal_payload = extract_all_signals(text_blob, key_features_list, epc_rating)
    listing_quality = float(signal_payload["listing_quality_score"])

    area_name = _resolve_area_name(address)
    zone_val = prop.get("zone")
    if isinstance(zone_val, int):
        zone = zone_val
    elif isinstance(zone_val, str) and zone_val.strip().isdigit():
        zone = int(zone_val.strip())
    else:
        zone = get_zone_from_address(address)

    price_score = _price_score(price)
    space_score = _space_score(bedrooms, property_type, price, floor_sq)
    location_score = _location_score(zone)
    commute_score, commute_distance_km = _commute_score(
        latitude, longitude, workplace_lat, workplace_lon
    )
    amenity_profile_score = _amenity_score(area_name)
    parking_sc = _parking_score(parking_status)
    freshness_sc = _freshness_score(
        str(first_visible_date) if first_visible_date is not None else None
    )
    data_quality_sc = _data_completeness_score(prop)
    amenity_tag_sc = _amenity_tag_score(amenity_tags)

    total_score = (
        price_score * weights["price"]
        + space_score * weights["space"]
        + location_score * weights["location"]
        + commute_score * weights["commute"]
        + amenity_profile_score * weights["amenity_profile"]
        + parking_sc * weights["parking"]
        + listing_quality * weights["listing_quality"]
        + freshness_sc * weights["freshness"]
        + amenity_tag_sc * weights["amenity_tags"]
        + data_quality_sc * weights["data_quality"]
    )

    tier = recommendation_tier(total_score)

    prop["total_score"] = round(total_score, 2)
    prop["recommendation_tier"] = tier
    prop["area"] = area_name
    prop["quality_signals"] = signal_payload["top_signals"]
    prop["listing_quality_score"] = signal_payload["listing_quality_score"]
    prop["scores"] = {
        "price": round(price_score, 1),
        "space": round(space_score, 1),
        "location": round(location_score, 1),
        "commute": round(commute_score, 1),
        "amenity_profile": round(amenity_profile_score, 1),
        "parking": round(parking_sc, 1),
        "listing_quality": round(listing_quality, 1),
        "freshness": round(freshness_sc, 1),
        "amenity_tags": round(amenity_tag_sc, 1),
        "data_quality": round(data_quality_sc, 1),
    }
    prop["signal_details"] = signal_payload
    prop["commute_distance_km"] = (
        round(commute_distance_km, 2) if isinstance(commute_distance_km, float) else None
    )


@tool
def search_london_rentals(
    max_top_picks: int = MAX_TOP_PICKS,
    max_trade_offs: int = MAX_TRADE_OFFS,
    sort_by: str = "newest",
) -> str:
    """Search rental properties across ALL of London. Always searches every borough — no area restriction.

    Returns two tiers:
    - top_picks: Properties matching all mandatory filters strictly (best matches).
    - with_trade_offs: Properties with one minor deviation (e.g. slightly over budget, further out).

    Args:
        max_top_picks: Maximum number of Top Picks to return (default 15).
        max_trade_offs: Maximum number of With Trade-offs to return (default 15).
        sort_by: Sort mode: "newest", "lowest_price", or "highest_price".

    Returns:
        JSON string containing top_picks, with_trade_offs, properties, filter_diagnostics.
    """
    # REGION^87490 is the only Rightmove identifier that reliably returns London
    # rentals. Borough-level REGION IDs return properties from other UK regions.
    # London-wide with full server-side filters (furnishTypes, minBathrooms)
    # yields resultCount~700, which drives pagination up to ~29 pages via the
    # resultCount-based pagination logic in _fetch_raw_properties_for_location.
    try:
        raw_all, strict_list, soft_list, rejected_reasons_by_property, areas_queried, _ = _run_search(
            areas=["London"],
            max_price=SOFT_MAX_PRICE,
            radius_miles=0.0,
            include_soft_tier=True,
            max_pages_per_location=MAX_PAGES_PER_LOCATION,
            max_results=max_top_picks + max_trade_offs,
            resolve_via_typeahead=False,
            sort_by=sort_by,
        )
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
        if isinstance(exc, httpx.HTTPStatusError) and getattr(exc.response, "status_code", 0) == 429:
            err_msg = "Rightmove rate-limited the request (429). Please retry shortly."
        else:
            err_msg = "Request to Rightmove failed."
        return json.dumps({"error": err_msg, "top_picks": [], "with_trade_offs": [], "properties": []})

    top_picks = [_extract_property(p) for p in strict_list[:max_top_picks]]
    trade_offs_parsed = [_extract_property(p) for p in soft_list[:max_trade_offs]]

    for i, prop in enumerate(soft_list[:max_trade_offs]):
        reasons = _get_soft_trade_off_reasons(prop)
        if reasons and i < len(trade_offs_parsed):
            trade_offs_parsed[i]["trade_off_reasons"] = reasons

    for prop in top_picks:
        _score_extracted_property(prop)
    for prop in trade_offs_parsed:
        _score_extracted_property(prop)

    top_picks.sort(key=lambda p: p.get("total_score", 0), reverse=True)
    trade_offs_parsed.sort(key=lambda p: p.get("total_score", 0), reverse=True)

    reject_reason_counts: dict[str, int] = {}
    for reasons in rejected_reasons_by_property:
        for r in reasons:
            reject_reason_counts[r] = reject_reason_counts.get(r, 0) + 1

    enforced_filters = {
        "min_bedrooms": MANDATORY_MIN_BEDROOMS,
        "min_bathrooms": MANDATORY_MIN_BATHROOMS,
        "parking_required": "soft — verified from listing text when available, otherwise flagged for agent confirmation",
        "furnished_required": True,
        "max_price_pcm": MANDATORY_MAX_PRICE,
        "max_distance_miles": MANDATORY_MAX_DISTANCE_MILES,
        "excluded_types": ["house share", "retirement home", "student accommodation"],
    }

    combined = top_picks + trade_offs_parsed

    scoring_summary = {
        "Highly Recommended": 0,
        "Worth Viewing": 0,
        "Consider If Flexible": 0,
        "Low Priority": 0,
    }
    for prop in combined:
        t = prop.get("recommendation_tier", "Low Priority")
        if t in scoring_summary:
            scoring_summary[t] += 1

    return json.dumps(
        {
            "search_scope": "london",
            "search_area": "London (all boroughs)",
            "areas_queried": areas_queried,
            "total_areas_searched": len(areas_queried),
            "raw_collected": len(raw_all),
            "total_results": len(combined),
            "top_picks_count": len(top_picks),
            "with_trade_offs_count": len(trade_offs_parsed),
            "enforced_filters": enforced_filters,
            "expansion_used": {"soft_max_price": SOFT_MAX_PRICE, "soft_max_distance_miles": SOFT_MAX_DISTANCE_MILES},
            "filter_diagnostics": {
                "accepted_count": len(strict_list) + len(soft_list),
                "returned_count": len(combined),
                "reject_reason_counts": reject_reason_counts,
                "constraint_impact_if_relaxed": _build_constraint_impact_summary(rejected_reasons_by_property),
            },
            "scoring_summary": scoring_summary,
            "top_picks": top_picks,
            "with_trade_offs": trade_offs_parsed,
            "properties": combined,
        }
    )
