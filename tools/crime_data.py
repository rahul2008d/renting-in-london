from __future__ import annotations

import json
import time

import httpx
from strands import tool

_API_BASE = "https://data.police.uk/api"
_TIMEOUT = 15
_MAX_RETRIES = 3
_BACKOFF = 2


def _fetch_crimes(lat: float, lon: float, date: str | None) -> tuple[list[dict], bool]:
    """Return (crimes, fell_back_to_latest) where fell_back_to_latest is True when the
    requested date returned a 404 or an empty list and the call was retried without a date."""
    url = f"{_API_BASE}/crimes-street/all-crime"

    def _attempt_fetch(client: httpx.Client, params: dict) -> list[dict] | None:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.get(url, params=params)
                if response.status_code in (429, 503):
                    time.sleep(_BACKOFF)
                    continue
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else None
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF)
        raise last_exc or RuntimeError("Failed to fetch crime data after retries")

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        params: dict[str, str | float] = {"lat": lat, "lng": lon}
        if date:
            params["date"] = date
            result = _attempt_fetch(client, params)
            if result is None or len(result) == 0:
                fallback_params: dict[str, str | float] = {"lat": lat, "lng": lon}
                fallback = _attempt_fetch(client, fallback_params)
                return (fallback or [], True)
            return (result, False)

        result = _attempt_fetch(client, params)
        return (result or [], False)


@tool
def get_crime_stats(lat: float, lon: float, date: str = "") -> str:
    """Fetch neighbourhood crime statistics from the UK Police API for a given location.

    Args:
        lat: Latitude of the property.
        lon: Longitude of the property.
        date: Optional month to query in YYYY-MM format. Defaults to latest available.

    Returns:
        JSON string with total_crimes, period, by_category, top_3_categories,
        safety_assessment, and coordinates.
    """
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return json.dumps({"error": "Invalid coordinates provided."})

    try:
        crimes, fell_back = _fetch_crimes(lat, lon, date or None)
    except Exception as exc:
        return json.dumps({"error": f"UK Police API request failed: {exc}"})

    by_category: dict[str, int] = {}
    period: str = date or ""
    for crime in crimes:
        category = crime.get("category", "unknown")
        by_category[category] = by_category.get(category, 0) + 1
        if not period and crime.get("month"):
            period = crime["month"]

    sorted_categories = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
    by_category_sorted = dict(sorted_categories)
    top_3 = [cat for cat, _ in sorted_categories[:3]]
    total = sum(by_category.values())

    if total <= 20:
        safety_assessment = "Low crime area"
    elif total <= 50:
        safety_assessment = "Moderate — typical for London"
    elif total <= 100:
        safety_assessment = "Above average — exercise normal caution"
    else:
        safety_assessment = "High crime density — research specific streets"

    result: dict = {
        "total_crimes": total,
        "period": period,
        "by_category": by_category_sorted,
        "top_3_categories": top_3,
        "safety_assessment": safety_assessment,
        "coordinates": {"lat": lat, "lon": lon},
    }
    if fell_back:
        result["period_note"] = (
            f"Requested date '{date}' returned no data; showing latest available month ({period})."
        )
    return json.dumps(result)
