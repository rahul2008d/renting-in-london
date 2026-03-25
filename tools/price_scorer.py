from __future__ import annotations

import json
import math
from datetime import date, datetime

from strands import tool

from data.area_profiles import get_profile
from data.london_areas import get_zone_from_address, search_areas
from tools.listing_signals import extract_all_signals, recommendation_tier

# `recommendation_tier` is defined in listing_signals; re-exported for imports from this module.

WEIGHT_PRESETS = {
    "balanced": {
        "price": 0.22,
        "space": 0.16,
        "location": 0.13,
        "commute": 0.12,
        "amenity_profile": 0.08,
        "parking": 0.08,
        "listing_quality": 0.10,
        "freshness": 0.05,
        "amenity_tags": 0.03,
        "data_quality": 0.03,
    },
    "budget": {
        "price": 0.40,
        "space": 0.15,
        "location": 0.08,
        "commute": 0.08,
        "amenity_profile": 0.05,
        "parking": 0.06,
        "listing_quality": 0.08,
        "freshness": 0.04,
        "amenity_tags": 0.03,
        "data_quality": 0.03,
    },
    "commute": {
        "price": 0.12,
        "space": 0.10,
        "location": 0.20,
        "commute": 0.30,
        "amenity_profile": 0.05,
        "parking": 0.06,
        "listing_quality": 0.07,
        "freshness": 0.04,
        "amenity_tags": 0.03,
        "data_quality": 0.03,
    },
    "space": {
        "price": 0.15,
        "space": 0.30,
        "location": 0.10,
        "commute": 0.10,
        "amenity_profile": 0.05,
        "parking": 0.06,
        "listing_quality": 0.10,
        "freshness": 0.04,
        "amenity_tags": 0.03,
        "data_quality": 0.07,
    },
    "amenities": {
        "price": 0.12,
        "space": 0.10,
        "location": 0.15,
        "commute": 0.10,
        "amenity_profile": 0.25,
        "parking": 0.05,
        "listing_quality": 0.08,
        "freshness": 0.04,
        "amenity_tags": 0.08,
        "data_quality": 0.03,
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
            combined: list[dict] = []
            for item in top_picks or []:
                if isinstance(item, dict):
                    tagged = dict(item)
                    tagged["_source_tier"] = "top_pick"
                    combined.append(tagged)
            for item in trade_offs or []:
                if isinstance(item, dict):
                    tagged = dict(item)
                    tagged["_source_tier"] = "trade_off"
                    combined.append(tagged)
            return combined

    return []


def _build_score_summary(ranked: list[dict]) -> dict[str, int]:
    return {
        "total_scored": len(ranked),
        "highly_recommended": sum(
            1 for r in ranked if r.get("recommendation_tier") == "Highly Recommended"
        ),
        "worth_viewing": sum(1 for r in ranked if r.get("recommendation_tier") == "Worth Viewing"),
        "consider_if_flexible": sum(
            1 for r in ranked if r.get("recommendation_tier") == "Consider If Flexible"
        ),
        "low_priority": sum(1 for r in ranked if r.get("recommendation_tier") == "Low Priority"),
        "from_top_picks": sum(1 for r in ranked if r.get("source_tier") == "top_pick"),
        "from_trade_offs": sum(1 for r in ranked if r.get("source_tier") == "trade_off"),
    }


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


def _price_score(price: float) -> float:
    if price <= 0:
        return 0.0
    if price <= 2300:
        return 50.0 + ((2300.0 - price) / 500.0) * 50.0
    return max(0.0, 50.0 - ((price - 2300.0) / 200.0) * 50.0)


def _space_score(
    bedrooms: int,
    property_type: str,
    price: float,
    floor_area_sqft: int | None,
) -> float:
    if floor_area_sqft is not None and floor_area_sqft > 0:
        base = min(100.0, floor_area_sqft / 15.0)
    else:
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


def _parking_score(parking_status: str) -> float:
    normalized = (parking_status or "").strip().lower()
    if normalized == "confirmed":
        return 100.0
    if normalized == "excluded":
        return 0.0
    if normalized == "unconfirmed":
        return 40.0
    return 40.0


def _parse_first_visible_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    try:
        normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _freshness_score(first_visible_date: str | None) -> float:
    d = _parse_first_visible_date(first_visible_date)
    if d is None:
        return 50.0
    days = (date.today() - d).days
    if days < 0:
        days = 0
    if days <= 7:
        return 100.0
    if days <= 14:
        return 70.0
    if days <= 21:
        return 40.0
    return 20.0


def _data_completeness_score(prop: dict) -> float:
    score = 0.0
    fa = prop.get("floor_area_sqft")
    if isinstance(fa, (int, float)) and fa > 0:
        score += 20.0
    kf = prop.get("key_features")
    if isinstance(kf, list) and len(kf) >= 3:
        score += 20.0
    ds = prop.get("display_size")
    if isinstance(ds, str) and ds.strip():
        score += 20.0
    elif ds not in (None, ""):
        score += 20.0
    imgs = prop.get("images")
    if isinstance(imgs, list) and len(imgs) > 0:
        score += 20.0
    lad = prop.get("let_available_date")
    if lad is not None and str(lad).strip():
        score += 20.0
    return min(100.0, score)


def _amenity_tag_score(amenity_tags: list | None) -> float:
    if not isinstance(amenity_tags, list):
        return 0.0
    return min(100.0, len(amenity_tags) * 12.0)


def _normalize_key_features(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item)
        elif isinstance(item, dict):
            d = item.get("description")
            if isinstance(d, str) and d.strip():
                out.append(d)
    return out


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
        empty_summary = {
            "total_scored": 0,
            "highly_recommended": 0,
            "worth_viewing": 0,
            "consider_if_flexible": 0,
            "low_priority": 0,
            "from_top_picks": 0,
            "from_trade_offs": 0,
        }
        return json.dumps(
            {
                "priorities": normalized_priorities,
                "weights": weights,
                "total_properties": 0,
                "summary": empty_summary,
                "ranked_properties": [],
            }
        )

    ranked: list[dict] = []
    for prop in properties:
        price = _to_float(prop.get("price_pcm"), 0.0)
        bedrooms = _to_int(prop.get("bedrooms"), 0)
        property_type = str(prop.get("property_type") or "")
        address = str(prop.get("address") or "")
        latitude = _to_float(prop.get("latitude"), 0.0)
        longitude = _to_float(prop.get("longitude"), 0.0)

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
            latitude,
            longitude,
            workplace_lat,
            workplace_lon,
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

        source_tier = prop.get("_source_tier")
        trade_offs_raw = prop.get("trade_off_reasons")
        trade_offs_list = trade_offs_raw if isinstance(trade_offs_raw, list) else []

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
                "source_tier": source_tier,
                "trade_off_reasons": trade_offs_list,
                "parking_status": parking_status,
                "amenity_tags": list(amenity_tags) if isinstance(amenity_tags, list) else [],
                "floor_area_sqft": floor_area_sqft if floor_area_sqft is not None else None,
                "first_visible_date": first_visible_date,
                "key_features": list(key_features_list),
                "scores": {
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
                },
                "listing_quality_score": signal_payload["listing_quality_score"],
                "quality_signals": signal_payload["top_signals"],
                "recommendation_tier": tier,
                "signal_details": signal_payload,
                "commute_distance_km": (
                    round(commute_distance_km, 2)
                    if isinstance(commute_distance_km, float)
                    else None
                ),
                "total_score": round(total_score, 2),
            }
        )

    ranked.sort(key=lambda item: item["total_score"], reverse=True)

    summary = _build_score_summary(ranked)

    return json.dumps(
        {
            "priorities": normalized_priorities,
            "weights": weights,
            "total_properties": len(ranked),
            "summary": summary,
            "ranked_properties": ranked,
        }
    )
