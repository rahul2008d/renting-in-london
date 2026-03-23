from __future__ import annotations

import json
import os
import re
import time

import httpx
from dotenv import load_dotenv
from strands import tool


TFL_PLACE_SEARCH_URL = "https://api.tfl.gov.uk/Place/Search"
TFL_JOURNEY_URL_TEMPLATE = "https://api.tfl.gov.uk/Journey/JourneyResults/{from_lat},{from_lon}/to/{to_lat},{to_lon}"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"

COORDINATE_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

load_dotenv()


COMMUTE_CACHE_TTL_SECONDS = 900
SERPAPI_COOLDOWN_SECONDS = 300
COMMUTE_CACHE: dict[str, tuple[float, str]] = {}
SERPAPI_DISABLED_UNTIL = 0.0


def _get_cache_key(
    from_lat: float,
    from_lon: float,
    to_location: str,
    arrive_by: str,
    cleaned_modes: str,
) -> str:
    destination = (to_location or "").strip().lower()
    return f"{from_lat:.5f}|{from_lon:.5f}|{destination}|{arrive_by}|{cleaned_modes}"


def _read_cached_commute(cache_key: str) -> str | None:
    payload = COMMUTE_CACHE.get(cache_key)
    if not payload:
        return None

    expiry_ts, result = payload
    if time.time() > expiry_ts:
        COMMUTE_CACHE.pop(cache_key, None)
        return None
    return result


def _write_cached_commute(cache_key: str, result: str) -> None:
    COMMUTE_CACHE[cache_key] = (time.time() + COMMUTE_CACHE_TTL_SECONDS, result)


def _serpapi_enabled() -> bool:
    global SERPAPI_DISABLED_UNTIL
    disable_flag = str(os.getenv("DISABLE_SERPAPI") or "").strip().lower()
    if disable_flag in {"1", "true", "yes", "on"}:
        return False
    if time.time() < SERPAPI_DISABLED_UNTIL:
        return False
    return True


def _parse_coordinates(value: str) -> tuple[float, float] | None:
    if not value:
        return None
    match = COORDINATE_PATTERN.match(value)
    if not match:
        return None
    try:
        latitude = float(match.group(1))
        longitude = float(match.group(2))
    except ValueError:
        return None
    return (latitude, longitude)


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_destination_coordinates(
    client: httpx.Client, to_location: str
) -> tuple[float, float, str] | tuple[None, None, str]:
    coordinates = _parse_coordinates(to_location)
    if coordinates:
        return coordinates[0], coordinates[1], to_location.strip()

    response = client.get(
        TFL_PLACE_SEARCH_URL,
        params={"name": to_location},
    )
    response.raise_for_status()

    data = response.json()

    places: list | None = None
    if isinstance(data, list):
        places = data
    elif isinstance(data, dict):
        if isinstance(data.get("places"), list):
            places = data.get("places")
        elif isinstance(data.get("matches"), list):
            places = data.get("matches")

    if not isinstance(places, list) or not places:
        return None, None, to_location

    for candidate in places:
        if not isinstance(candidate, dict):
            continue
        latitude = _coerce_float(candidate.get("lat"))
        longitude = _coerce_float(candidate.get("lon"))
        if latitude is None or longitude is None:
            continue
        resolved_name = (
            candidate.get("commonName")
            if isinstance(candidate.get("commonName"), str)
            else to_location
        )
        return latitude, longitude, resolved_name

    return None, None, to_location


def _format_journey_option(journey: dict) -> dict:
    legs = journey.get("legs") if isinstance(journey.get("legs"), list) else []

    modes_used: list[str] = []
    formatted_legs: list[dict] = []
    transit_lines: list[str] = []
    walking_minutes = 0

    for leg in legs:
        if not isinstance(leg, dict):
            continue

        mode_name = None
        mode_data = leg.get("mode")
        if isinstance(mode_data, dict):
            raw_mode_name = mode_data.get("name")
            if isinstance(raw_mode_name, str):
                mode_name = raw_mode_name

        if mode_name and mode_name not in modes_used:
            modes_used.append(mode_name)

        if mode_name == "walking":
            leg_duration = leg.get("duration")
            if isinstance(leg_duration, (int, float)):
                walking_minutes += int(round(float(leg_duration)))

        route_options = leg.get("routeOptions") if isinstance(leg.get("routeOptions"), list) else []
        if route_options and isinstance(route_options[0], dict):
            line_name = route_options[0].get("name")
            if isinstance(line_name, str) and line_name.strip() and line_name not in transit_lines:
                transit_lines.append(line_name.strip())

        instruction_data = leg.get("instruction") if isinstance(leg.get("instruction"), dict) else {}
        summary = instruction_data.get("summary") if isinstance(instruction_data.get("summary"), str) else None

        formatted_legs.append(
            {
                "mode": mode_name,
                "instruction": summary,
                "departure_time": leg.get("departureTime"),
                "arrival_time": leg.get("arrivalTime"),
            }
        )

    duration = journey.get("duration")
    duration_value = int(duration) if isinstance(duration, (int, float)) else None
    number_of_changes = max(len(legs) - 1, 0)

    departure_time = legs[0].get("departureTime") if legs and isinstance(legs[0], dict) else None
    arrival_time = legs[-1].get("arrivalTime") if legs and isinstance(legs[-1], dict) else None

    return {
        "total_duration_minutes": duration_value,
        "number_of_changes": number_of_changes,
        "modes_used": modes_used,
        "transit_lines": transit_lines,
        "walking_minutes": walking_minutes,
        "departure_time": departure_time,
        "arrival_time": arrival_time,
        "legs": formatted_legs,
    }


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "")


def _format_google_route(route: dict) -> dict:
    legs = route.get("legs") if isinstance(route.get("legs"), list) else []
    if not legs or not isinstance(legs[0], dict):
        return {
            "total_duration_minutes": None,
            "number_of_changes": 0,
            "modes_used": [],
            "departure_time": None,
            "arrival_time": None,
            "legs": [],
        }

    primary_leg = legs[0]
    steps = primary_leg.get("steps") if isinstance(primary_leg.get("steps"), list) else []

    modes_used: list[str] = []
    formatted_legs: list[dict] = []
    transit_steps = 0
    transit_lines: list[str] = []
    walking_minutes = 0

    for step in steps:
        if not isinstance(step, dict):
            continue

        mode = str(step.get("travel_mode") or "").lower()
        if mode == "transit":
            transit_steps += 1
            transit_details = step.get("transit_details") if isinstance(step.get("transit_details"), dict) else {}
            line = transit_details.get("line") if isinstance(transit_details.get("line"), dict) else {}
            vehicle = line.get("vehicle") if isinstance(line.get("vehicle"), dict) else {}
            vehicle_type = str(vehicle.get("type") or "transit").lower()
            line_name = line.get("short_name") or line.get("name") or vehicle_type
            mode_label = f"{vehicle_type}:{line_name}"
            if isinstance(line_name, str) and line_name.strip() and line_name not in transit_lines:
                transit_lines.append(line_name.strip())
        else:
            mode_label = mode or "walking"

        if mode == "walking":
            step_duration = step.get("duration") if isinstance(step.get("duration"), dict) else {}
            duration_seconds = step_duration.get("value")
            if isinstance(duration_seconds, (int, float)):
                walking_minutes += int(round(float(duration_seconds) / 60.0))

        if mode_label and mode_label not in modes_used:
            modes_used.append(mode_label)

        instruction = _strip_html(str(step.get("html_instructions") or ""))
        formatted_legs.append(
            {
                "mode": mode_label,
                "instruction": instruction,
                "departure_time": None,
                "arrival_time": None,
            }
        )

    duration_data = primary_leg.get("duration") if isinstance(primary_leg.get("duration"), dict) else {}
    duration_seconds = duration_data.get("value")
    duration_minutes = int(round(float(duration_seconds) / 60.0)) if isinstance(duration_seconds, (int, float)) else None

    departure = primary_leg.get("departure_time") if isinstance(primary_leg.get("departure_time"), dict) else {}
    arrival = primary_leg.get("arrival_time") if isinstance(primary_leg.get("arrival_time"), dict) else {}

    number_of_changes = max(transit_steps - 1, 0)

    return {
        "total_duration_minutes": duration_minutes,
        "number_of_changes": number_of_changes,
        "modes_used": modes_used,
        "transit_lines": transit_lines,
        "walking_minutes": walking_minutes,
        "departure_time": departure.get("text"),
        "arrival_time": arrival.get("text"),
        "legs": formatted_legs,
    }


def _try_google_commute(
    client: httpx.Client,
    from_lat: float,
    from_lon: float,
    to_location: str,
) -> dict | None:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None

    try:
        response = client.get(
            GOOGLE_DIRECTIONS_URL,
            params={
                "origin": f"{from_lat},{from_lon}",
                "destination": to_location,
                "mode": "transit",
                "alternatives": "true",
                "departure_time": "now",
                "key": api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError):
        return None

    status = payload.get("status") if isinstance(payload, dict) else None
    if status != "OK":
        return None

    routes = payload.get("routes") if isinstance(payload.get("routes"), list) else []
    options = [_format_google_route(route) for route in routes if isinstance(route, dict)]
    options = [opt for opt in options if isinstance(opt.get("total_duration_minutes"), int)]
    options.sort(key=lambda option: option.get("total_duration_minutes") or 10**9)
    top_three = options[:3]
    if not top_three:
        return None

    return {
        "provider": "google_maps",
        "from": {"lat": from_lat, "lon": from_lon},
        "to": {
            "input": to_location,
            "resolved_name": to_location,
            "lat": None,
            "lon": None,
        },
        "arrive_by": "flexible",
        "modes": "transit",
        "total_options": len(top_three),
        "journey_options": top_three,
    }


def _extract_serpapi_modes(direction: dict) -> list[str]:
    trips = direction.get("trips") if isinstance(direction.get("trips"), list) else []
    modes: list[str] = []
    for trip in trips:
        if not isinstance(trip, dict):
            continue
        mode = str(trip.get("travel_mode") or "").strip().lower()
        if mode and mode not in modes:
            modes.append(mode)

    primary_mode = str(direction.get("travel_mode") or "").strip().lower()
    if primary_mode and primary_mode not in modes:
        modes.insert(0, primary_mode)
    return modes


def _format_serpapi_direction(direction: dict) -> dict:
    duration_seconds = direction.get("duration")
    duration_minutes = None
    if isinstance(duration_seconds, (int, float)):
        duration_minutes = int(round(float(duration_seconds) / 60.0))

    via = direction.get("via") if isinstance(direction.get("via"), str) else None
    trips = direction.get("trips") if isinstance(direction.get("trips"), list) else []
    transit_trip_count = 0
    formatted_legs: list[dict] = []
    transit_lines: list[str] = []
    walking_minutes = 0

    for trip in trips:
        if not isinstance(trip, dict):
            continue
        mode = str(trip.get("travel_mode") or "").strip().lower()
        if mode == "transit":
            transit_trip_count += 1
            line_name = trip.get("title")
            if isinstance(line_name, str) and line_name.strip() and line_name not in transit_lines:
                transit_lines.append(line_name.strip())
        if mode == "walking":
            trip_duration = trip.get("duration")
            if isinstance(trip_duration, (int, float)):
                walking_minutes += int(round(float(trip_duration) / 60.0))
        formatted_legs.append(
            {
                "mode": mode or None,
                "instruction": trip.get("title"),
                "departure_time": ((trip.get("start_stop") or {}).get("time") if isinstance(trip.get("start_stop"), dict) else None),
                "arrival_time": ((trip.get("end_stop") or {}).get("time") if isinstance(trip.get("end_stop"), dict) else None),
            }
        )

    number_of_changes = max(transit_trip_count - 1, 0)
    if transit_trip_count == 0:
        number_of_changes = max(len(trips) - 1, 0)

    return {
        "total_duration_minutes": duration_minutes,
        "number_of_changes": number_of_changes,
        "modes_used": _extract_serpapi_modes(direction),
        "transit_lines": transit_lines,
        "walking_minutes": walking_minutes,
        "departure_time": direction.get("start_time"),
        "arrival_time": direction.get("end_time"),
        "route_summary": via,
        "legs": formatted_legs,
    }


def _try_serpapi_google_maps_commute(
    client: httpx.Client,
    from_lat: float,
    from_lon: float,
    to_location: str,
) -> dict | None:
    global SERPAPI_DISABLED_UNTIL
    if not _serpapi_enabled():
        return None

    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERP_API_KEY")
    if not api_key:
        return None

    try:
        response = client.get(
            SERPAPI_SEARCH_URL,
            params={
                "engine": "google_maps_directions",
                "start_coords": f"{from_lat},{from_lon}",
                "end_addr": to_location,
                "travel_mode": "3",  # Transit
                "prefer": "subway,train",
                "time": f"depart_at:{int(time.time())}",
                "hl": "en",
                "gl": "uk",
                "api_key": api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403, 429}:
            SERPAPI_DISABLED_UNTIL = time.time() + SERPAPI_COOLDOWN_SECONDS
        return None
    except (httpx.RequestError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get("error"), str) and payload.get("error"):
        SERPAPI_DISABLED_UNTIL = time.time() + SERPAPI_COOLDOWN_SECONDS
        return None

    directions = payload.get("directions") if isinstance(payload.get("directions"), list) else []
    transit_or_mixed = [
        d for d in directions
        if isinstance(d, dict) and str(d.get("travel_mode") or "").lower() in {"transit", "mixed"}
    ]
    usable = transit_or_mixed if transit_or_mixed else [d for d in directions if isinstance(d, dict)]
    if not usable:
        return None

    options = [_format_serpapi_direction(direction) for direction in usable]
    options = [opt for opt in options if isinstance(opt.get("total_duration_minutes"), int)]
    options.sort(key=lambda option: option.get("total_duration_minutes") or 10**9)
    top_three = options[:3]
    if not top_three:
        return None

    places_info = payload.get("places_info") if isinstance(payload.get("places_info"), list) else []
    resolved_destination = to_location
    to_lat = None
    to_lon = None
    if len(places_info) >= 2 and isinstance(places_info[1], dict):
        place = places_info[1]
        address = place.get("address")
        if isinstance(address, str) and address.strip():
            resolved_destination = address
        coords = place.get("gps_coordinates") if isinstance(place.get("gps_coordinates"), dict) else {}
        to_lat = _coerce_float(coords.get("latitude"))
        to_lon = _coerce_float(coords.get("longitude"))

    return {
        "provider": "serpapi_google_maps",
        "from": {"lat": from_lat, "lon": from_lon},
        "to": {
            "input": to_location,
            "resolved_name": resolved_destination,
            "lat": to_lat,
            "lon": to_lon,
        },
        "arrive_by": "flexible",
        "modes": "transit",
        "total_options": len(top_three),
        "journey_options": top_three,
        "source_url": payload.get("search_metadata", {}).get("google_maps_directions_url") if isinstance(payload.get("search_metadata"), dict) else None,
    }


@tool
def calculate_commute(
    from_lat: float,
    from_lon: float,
    to_location: str,
    arrive_by: str = "0830",
    modes: str = "tube,bus,walking",
) -> str:
    """Calculate commute time from a property location to a destination using TfL.

    Args:
        from_lat: Origin latitude (property location).
        from_lon: Origin longitude (property location).
        to_location: Destination place name or coordinate string ("lat,lon").
        arrive_by: Target arrival time in HHMM 24-hour format.
        modes: Comma-separated TfL modes (for example: "tube,bus,walking").

    Returns:
        JSON string with up to top 3 journey options sorted by shortest duration,
        including total duration, changes, modes, departure/arrival times, and leg summaries.
        On error, returns JSON string with an "error" field.
    """
    if not to_location or not to_location.strip():
        return json.dumps({"error": "to_location is required."})

    cleaned_modes = ",".join(
        [part.strip() for part in (modes or "").split(",") if part.strip()]
    )
    if not cleaned_modes:
        cleaned_modes = "tube,bus,walking"

    cache_key = _get_cache_key(from_lat, from_lon, to_location, arrive_by, cleaned_modes)
    cached = _read_cached_commute(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            serpapi_payload = _try_serpapi_google_maps_commute(client, from_lat, from_lon, to_location)
            if isinstance(serpapi_payload, dict):
                result = json.dumps(serpapi_payload)
                _write_cached_commute(cache_key, result)
                return result

            google_payload = _try_google_commute(client, from_lat, from_lon, to_location)
            if isinstance(google_payload, dict):
                result = json.dumps(google_payload)
                _write_cached_commute(cache_key, result)
                return result

            to_lat, to_lon, resolved_destination = _resolve_destination_coordinates(client, to_location)
            if to_lat is None or to_lon is None:
                result = json.dumps(
                    {
                        "error": f"Could not resolve destination '{to_location}' via TfL Place Search.",
                        "from": {"lat": from_lat, "lon": from_lon},
                        "to_location": to_location,
                    }
                )
                _write_cached_commute(cache_key, result)
                return result

            journey_url = TFL_JOURNEY_URL_TEMPLATE.format(
                from_lat=from_lat,
                from_lon=from_lon,
                to_lat=to_lat,
                to_lon=to_lon,
            )
            journey_response = client.get(
                journey_url,
                params={
                    "mode": cleaned_modes,
                    "time": arrive_by,
                    "timeIs": "arriving",
                },
            )
            journey_response.raise_for_status()

        journey_data = journey_response.json()

    except httpx.TimeoutException:
        result = json.dumps(
            {
                "error": "TfL API request timed out.",
                "from": {"lat": from_lat, "lon": from_lon},
                "to_location": to_location,
            }
        )
        return result
    except httpx.HTTPStatusError as exc:
        result = json.dumps(
            {
                "error": f"TfL API returned HTTP {exc.response.status_code}.",
                "from": {"lat": from_lat, "lon": from_lon},
                "to_location": to_location,
            }
        )
        return result
    except httpx.RequestError as exc:
        result = json.dumps(
            {
                "error": f"Network error calling TfL API: {exc.__class__.__name__}.",
                "from": {"lat": from_lat, "lon": from_lon},
                "to_location": to_location,
            }
        )
        return result
    except json.JSONDecodeError:
        result = json.dumps(
            {
                "error": "TfL API returned invalid JSON.",
                "from": {"lat": from_lat, "lon": from_lon},
                "to_location": to_location,
            }
        )
        return result

    journeys = journey_data.get("journeys") if isinstance(journey_data, dict) else None
    if not isinstance(journeys, list):
        result = json.dumps(
            {
                "error": "Unexpected TfL Journey Planner response format: missing journeys array.",
                "from": {"lat": from_lat, "lon": from_lon},
                "to_location": to_location,
            }
        )
        return result

    journey_options = [
        _format_journey_option(journey)
        for journey in journeys
        if isinstance(journey, dict)
    ]
    journey_options.sort(
        key=lambda option: option["total_duration_minutes"]
        if isinstance(option.get("total_duration_minutes"), int)
        else 10**9
    )
    top_three = journey_options[:3]

    result = json.dumps(
        {
            "provider": "tfl",
            "from": {"lat": from_lat, "lon": from_lon},
            "to": {
                "input": to_location,
                "resolved_name": resolved_destination,
                "lat": to_lat,
                "lon": to_lon,
            },
            "arrive_by": arrive_by,
            "modes": cleaned_modes,
            "total_options": len(top_three),
            "journey_options": top_three,
        }
    )
    _write_cached_commute(cache_key, result)
    return result
