from __future__ import annotations

import json
import re

from strands import tool


MANDATORY_MAX_PRICE = 2300
MANDATORY_MIN_BEDROOMS = 2
MANDATORY_MIN_BATHROOMS = 2
MANDATORY_MAX_DISTANCE_MILES = 5.0
SOFT_MAX_PRICE = 2500
SOFT_MAX_DISTANCE_MILES = 7.0
DEFAULT_MAX_PER_BUCKET = 15


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _joined_text(prop: dict) -> str:
    parts: list[str] = []

    for key in ("summary", "property_type", "property_type_full", "display_status"):
        value = prop.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    key_features = prop.get("key_features")
    if isinstance(key_features, list):
        for feature in key_features:
            if isinstance(feature, str) and feature.strip():
                parts.append(feature.strip())

    return " ".join(parts).lower()


def _fallback_mandatory_checks(prop: dict) -> dict[str, bool]:
    price = _to_int(prop.get("price_pcm"), 0)
    bedrooms = _to_int(prop.get("bedrooms"), 0)
    bathrooms = _to_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance_miles"))

    text_blob = _joined_text(prop)

    parking_ok = any(term in text_blob for term in [
        "parking", "garage", "driveway", "off street", "off-street",
        "car port", "carport", "allocated parking", "allocated space",
        "parking permit", "residents permit", "car space", "private parking",
        "resident parking", "residents parking", "on-site parking",
        "onsite parking", "visitor parking",
    ])
    furnished_ok = not re.search(r"(?<!or\s)(?<!/\s)unfurnished", text_blob)
    excluded_ok = not any(
        term in text_blob
        for term in ["house share", "retirement", "student accommodation", "student accomodation"]
    ) and not bool(prop.get("students"))

    return {
        "price_ok": price > 0 and price <= MANDATORY_MAX_PRICE,
        "bedrooms_ok": bedrooms >= MANDATORY_MIN_BEDROOMS,
        "bathrooms_ok": bathrooms >= MANDATORY_MIN_BATHROOMS,
        "distance_ok": distance is None or distance <= MANDATORY_MAX_DISTANCE_MILES,
        "parking_ok": parking_ok,
        "furnished_ok": furnished_ok,
        "excluded_type_ok": excluded_ok,
    }


def _is_soft_trade_off(prop: dict) -> bool:
    """Check if property is in 'With Trade-offs' tier (single minor deviation)."""
    price = _to_int(prop.get("price_pcm"), 0)
    bedrooms = _to_int(prop.get("bedrooms"), 0)
    bathrooms = _to_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance_miles"))

    if bedrooms < MANDATORY_MIN_BEDROOMS:
        return False

    checks = _fallback_mandatory_checks(prop)
    if all(checks.values()):
        return False

    soft_deviations = 0
    if not checks["price_ok"] and MANDATORY_MAX_PRICE < price <= SOFT_MAX_PRICE:
        soft_deviations += 1
    if not checks["bathrooms_ok"] and bathrooms == 1:
        soft_deviations += 1
    if not checks["distance_ok"] and distance and MANDATORY_MAX_DISTANCE_MILES < distance <= SOFT_MAX_DISTANCE_MILES:
        soft_deviations += 1
    if not checks["parking_ok"]:
        soft_deviations += 1

    return soft_deviations == 1 and checks["furnished_ok"] and checks["excluded_type_ok"]


def _extract_fail_reasons(checks: dict[str, bool]) -> list[str]:
    mapping = {
        "price_ok": f"Rent above GBP {MANDATORY_MAX_PRICE} pcm",
        "bedrooms_ok": f"Below {MANDATORY_MIN_BEDROOMS} bedrooms",
        "bathrooms_ok": f"Below {MANDATORY_MIN_BATHROOMS} bathrooms",
        "distance_ok": f"Beyond {MANDATORY_MAX_DISTANCE_MILES} miles",
        "parking_ok": "No clear parking signal",
        "furnished_ok": "No clear furnished signal",
        "excluded_type_ok": "Excluded listing type",
    }

    reasons: list[str] = []
    for key, message in mapping.items():
        if not checks.get(key, False):
            reasons.append(message)
    return reasons


def _risk_flags(prop: dict) -> list[str]:
    text_blob = _joined_text(prop)
    signals = {
        "potentially compact layout": ["compact", "cosy", "cozy"],
        "possible noise exposure": ["busy road", "high street", "main road"],
        "ground-floor tradeoff": ["ground floor"],
        "short-let caveat": ["short let", "short-let"],
    }

    risks: list[str] = []
    for label, terms in signals.items():
        if any(term in text_blob for term in terms):
            risks.append(label)

    return risks


def _soft_score(prop: dict) -> tuple[float, dict[str, float]]:
    price = _to_int(prop.get("price_pcm"), 0)
    bedrooms = _to_int(prop.get("bedrooms"), 0)
    bathrooms = _to_int(prop.get("bathrooms"), 0)
    distance = _to_float(prop.get("distance_miles"))

    price_component = 0.0
    if price > 0:
        price_component = max(0.0, min(35.0, ((MANDATORY_MAX_PRICE - price) / MANDATORY_MAX_PRICE) * 35.0))

    space_component = min(30.0, max(0.0, bedrooms * 8.0 + bathrooms * 7.0))

    distance_component = 20.0
    if isinstance(distance, float):
        distance_component = max(0.0, 20.0 - (distance * 3.0))

    info_richness = 0.0
    features = prop.get("key_features")
    if isinstance(features, list):
        info_richness += min(10.0, len(features) * 1.25)
    summary = prop.get("summary")
    if isinstance(summary, str) and summary.strip():
        info_richness += min(5.0, len(summary.strip()) / 120.0)

    breakdown = {
        "price": round(price_component, 2),
        "space": round(space_component, 2),
        "distance": round(distance_component, 2),
        "listing_quality": round(min(15.0, info_richness), 2),
    }

    total = sum(breakdown.values())
    return round(max(0.0, min(100.0, total)), 2), breakdown


def _decision_label(score: float, risk_count: int) -> str:
    if score >= 58.0 and risk_count <= 1:
        return "Strong Match"
    if score >= 42.0:
        return "Maybe"
    return "Reject"


@tool
def rank_property_decisions(
    properties_json: str,
    max_per_bucket: int = DEFAULT_MAX_PER_BUCKET,
    include_reject_items: bool = False,
) -> str:
    """Classify properties into Strong Match, Maybe, and Reject with reasons.

    Args:
        properties_json: JSON string from search_london_rentals (top_picks + with_trade_offs), or a JSON
            list of property dictionaries.
        max_per_bucket: Maximum number of items to return per decision bucket.
            Summary counts still reflect all classified properties.
        include_reject_items: Whether to include full reject property items.
            Defaults to False to keep payload compact for multi-area workflows.

    Returns:
        JSON string with decision buckets and rationale for each property.
        Fields include strong_matches, maybe_matches, rejects, and summary counts.
        Returns an error JSON payload if input is invalid.
    """
    if not properties_json or not properties_json.strip():
        return json.dumps({"error": "properties_json is required."})

    safe_max_per_bucket = max(1, min(int(max_per_bucket or DEFAULT_MAX_PER_BUCKET), 20))

    try:
        payload = json.loads(properties_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "properties_json is not valid JSON."})

    properties = _extract_properties(payload)
    if not properties:
        return json.dumps(
            {
                "total_input_properties": 0,
                "strong_matches": [],
                "maybe_matches": [],
                "rejects": [],
                "summary": {
                    "strong_match_count": 0,
                    "maybe_count": 0,
                    "reject_count": 0,
                },
            }
        )

    strong_matches: list[dict] = []
    maybe_matches: list[dict] = []
    rejects: list[dict] = []

    for prop in properties:
        checks = prop.get("mandatory_checks") if isinstance(prop.get("mandatory_checks"), dict) else None
        if checks is None:
            checks = _fallback_mandatory_checks(prop)

        failed_reasons = _extract_fail_reasons(checks)
        risk_flags = _risk_flags(prop)
        score, score_breakdown = _soft_score(prop)
        label = _decision_label(score, len(risk_flags))

        if failed_reasons:
            if _is_soft_trade_off(prop):
                label = "Maybe"
            else:
                label = "Reject"

        item = {
            "id": prop.get("id"),
            "address": prop.get("address"),
            "url": prop.get("url"),
            "price_pcm": prop.get("price_pcm"),
            "price_display": prop.get("price_display"),
            "bedrooms": prop.get("bedrooms"),
            "bathrooms": prop.get("bathrooms"),
            "distance_miles": prop.get("distance_miles"),
            "formatted_distance": prop.get("formatted_distance"),
            "latitude": prop.get("latitude"),
            "longitude": prop.get("longitude"),
            "property_type": prop.get("property_type"),
            "property_type_full": prop.get("property_type_full"),
            "display_size": prop.get("display_size"),
            "agent": prop.get("agent"),
            "branch": prop.get("branch"),
            "decision": label,
            "decision_score": score,
            "match_highlights": prop.get("match_summary") if isinstance(prop.get("match_summary"), list) else [],
            "key_features": (prop.get("key_features")[:5] if isinstance(prop.get("key_features"), list) else []),
            "risk_flags": risk_flags,
            "reject_reasons": failed_reasons,
        }

        if label == "Strong Match":
            strong_matches.append(item)
        elif label == "Maybe":
            maybe_matches.append(item)
        else:
            rejects.append(item)

    strong_matches.sort(key=lambda item: item.get("decision_score", 0), reverse=True)
    maybe_matches.sort(key=lambda item: item.get("decision_score", 0), reverse=True)
    rejects.sort(key=lambda item: item.get("decision_score", 0), reverse=True)

    strong_trimmed = strong_matches[:safe_max_per_bucket]
    maybe_trimmed = maybe_matches[:safe_max_per_bucket]
    reject_trimmed = rejects[:safe_max_per_bucket] if include_reject_items else []

    return json.dumps(
        {
            "total_input_properties": len(properties),
            "strong_matches": strong_trimmed,
            "maybe_matches": maybe_trimmed,
            "rejects": reject_trimmed,
            "summary": {
                "strong_match_count": len(strong_matches),
                "maybe_count": len(maybe_matches),
                "reject_count": len(rejects),
            },
            "response_limits": {
                "max_per_bucket": safe_max_per_bucket,
                "include_reject_items": include_reject_items,
            },
        }
    )
