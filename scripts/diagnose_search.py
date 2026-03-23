#!/usr/bin/env python3
"""Diagnostic script to investigate zero search results. Run: uv run python scripts/diagnose_search.py"""

from __future__ import annotations

import json
import sys

# Add project root to path
sys.path.insert(0, ".")

from data.london_areas import get_location_id, get_london_borough_areas, LONDON_WIDE_LOCATION_ID
from tools.rightmove_search import (
    RIGHTMOVE_SEARCH_API,
    RIGHTMOVE_REFERER,
    HEADERS,
    PAGE_SIZE,
    SOFT_MAX_PRICE,
    SOFT_MAX_DISTANCE_MILES,
    MANDATORY_MAX_PRICE,
    MANDATORY_MIN_BEDROOMS,
    MANDATORY_MIN_BATHROOMS,
    MANDATORY_MAX_DISTANCE_MILES,
    _run_search,
    _collect_text_fields,
    _has_parking,
    _is_furnished,
    _is_excluded_type,
    _mandatory_reject_reasons,
    _extract_properties_from_next_data_html,
)


def main() -> None:
    print("=" * 60)
    print("SEARCH DIAGNOSTIC")
    print("=" * 60)

    # 1. Check borough config
    boroughs = get_london_borough_areas()
    print(f"\n1. Boroughs configured: {len(boroughs)}")
    sample = boroughs[:5]
    for b in sample:
        lid = get_location_id(b)
        print(f"   - {b!r} -> {lid!r}")
    if not boroughs:
        print("   ERROR: No boroughs!")
        return

    # 2. Direct API call for London-wide (REGION^87490)
    import httpx

    loc_id = get_location_id("London") or LONDON_WIDE_LOCATION_ID
    if not loc_id:
        print("\n2. ERROR: No location ID for Camden")
        return

    params = {
        "channel": "RENT",
        "maxPrice": SOFT_MAX_PRICE,
        "minBedrooms": MANDATORY_MIN_BEDROOMS,
        "maxBedrooms": 4,
        "numberOfPropertiesPerPage": PAGE_SIZE,
        "sortType": 6,  # newest
        "includeLetAgreed": "false",
        "currencyCode": "GBP",
        "areaSizeUnit": "miles",
        "radius": SOFT_MAX_DISTANCE_MILES,
        "locationIdentifier": loc_id,
        "index": 0,
    }

    print(f"\n2. Direct API call: London ({loc_id})")
    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        resp = client.get(RIGHTMOVE_SEARCH_API, params=params)
        print(f"   Status: {resp.status_code}")
        print(f"   Content-Type: {resp.headers.get('content-type')}")
        if resp.status_code != 200:
            print(f"   Body: {resp.text[:500]}")
            return

        try:
            data = resp.json()
        except Exception as e:
            print(f"   API returned non-JSON (likely HTML error page): {e}")
            print(f"   Body preview: {resp.text[:200]!r}...")
            data = None

        props: list = []
        if isinstance(data, dict):
            props = data.get("properties") or []
        result_count = data.get("resultCount", 0) if isinstance(data, dict) else 0
        print(f"   resultCount: {result_count}")
        print(f"   properties returned: {len(props)}")

        if props:
            p = props[0]
            print(f"\n   Sample property keys: {list(p.keys())}")
            print(f"   - id: {p.get('id')}")
            print(f"   - price.amount: {p.get('price', {}).get('amount')}")
            print(f"   - bedrooms: {p.get('bedrooms')}")
            print(f"   - bathrooms: {p.get('bathrooms')}")
            print(f"   - distance: {p.get('distance')} (type: {type(p.get('distance'))})")
            print(f"   - displayAddress: {p.get('displayAddress')}")
            text = _collect_text_fields(p)
            print(f"   - text_blob (len {len(text)}): {repr(text[:200])}...")
            print(f"   - _has_parking: {_has_parking(text)}")
            print(f"   - _is_furnished: {_is_furnished(text)}")
            print(f"   - _is_excluded: {_is_excluded_type(p, text)}")
            reasons = _mandatory_reject_reasons(p)
            print(f"   - reject_reasons: {reasons}")

            # Count reject reasons across first 20
            reason_counts: dict[str, int] = {}
            for prop in props[:50]:
                r = _mandatory_reject_reasons(prop)
                for reason in r:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            print(f"\n   Reject reason counts (first 50): {reason_counts}")
        else:
            print("   No properties in API response.")

    # 2b. Fallback: fetch find.html page (used when API returns HTML)
    print("\n2b. Fallback: fetch find.html")
    find_params = {
        "locationIdentifier": loc_id,
        "minBedrooms": MANDATORY_MIN_BEDROOMS,
        "maxBedrooms": 4,
        "maxPrice": SOFT_MAX_PRICE,
        "channel": "RENT",
    }
    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        resp = client.get(RIGHTMOVE_REFERER, params=find_params)
        print(f"   Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type')}")
        print(f"   Has __NEXT_DATA__: {'__NEXT_DATA__' in resp.text}, body len: {len(resp.text)}")
        page_props, result_count = _extract_properties_from_next_data_html(resp.text)
        print(f"   Extracted from __NEXT_DATA__: {len(page_props) if page_props else 0} properties, resultCount={result_count}")
        if page_props and len(page_props) > 0:
            p = page_props[0]
            print(f"   Sample: id={p.get('id')}, price={p.get('price', {}).get('amount')}, beds={p.get('bedrooms')}, baths={p.get('bathrooms')}, distance={p.get('distance')}")
            reason_counts: dict[str, int] = {}
            for prop in page_props[:50]:
                r = _mandatory_reject_reasons(prop)
                for reason in r:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            print(f"   Reject reason counts: {reason_counts}")

    # 3. Run full search (London-wide)
    print("\n3. Full _run_search (London-wide)")
    try:
        raw_all, strict_list, soft_list, rejected_reasons, areas_queried, _ = _run_search(
            areas=["London"],
            max_price=SOFT_MAX_PRICE,
            radius_miles=SOFT_MAX_DISTANCE_MILES,
            include_soft_tier=True,
            max_pages_per_location=4,
            max_results=50,
            resolve_via_typeahead=False,
        )
        print(f"   raw_collected: {len(raw_all)}")
        print(f"   strict (top_picks): {len(strict_list)}")
        print(f"   soft (trade_offs): {len(soft_list)}")
        print(f"   areas_queried: {areas_queried}")

        if rejected_reasons:
            reason_totals: dict[str, int] = {}
            for reasons in rejected_reasons:
                for r in reasons:
                    reason_totals[r] = reason_totals.get(r, 0) + 1
            print(f"   reject_reason_totals: {reason_totals}")
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
