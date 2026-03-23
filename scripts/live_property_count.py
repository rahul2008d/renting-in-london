#!/usr/bin/env python3
"""Quick live test: fetch and count properties from a small sample of boroughs.

Usage: python scripts/live_property_count.py
Time: ~30-60 seconds (3 boroughs, 2 pages each, with rate-limit sleeps).
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, ".")

import httpx

from data.london_areas import get_location_id, get_london_borough_areas
from tools.rightmove_search import (
    RIGHTMOVE_SEARCH_API,
    HEADERS,
    PAGE_SIZE,
    SOFT_MAX_PRICE,
    MANDATORY_MIN_BEDROOMS,
    MANDATORY_MIN_BATHROOMS,
    _fetch_raw_properties_for_location,
    _mandatory_reject_reasons,
    _passes_soft_filters,
)

SAMPLE_BOROUGHS = ["Camden", "Hackney", "Islington", "Southwark", "Tower Hamlets"]
MAX_PAGES = 2  # Keep the live test short


def main() -> None:
    boroughs = get_london_borough_areas()
    print(f"Total REGION boroughs configured: {len(boroughs)}")
    print(f"\nSampling {len(SAMPLE_BOROUGHS)} boroughs with {MAX_PAGES} pages each...")
    print("=" * 60)

    params: dict = {
        "channel": "RENT",
        "maxPrice": SOFT_MAX_PRICE,
        "minBedrooms": MANDATORY_MIN_BEDROOMS,
        "maxBedrooms": 4,
        "minBathrooms": MANDATORY_MIN_BATHROOMS,
        "numberOfPropertiesPerPage": PAGE_SIZE,
        "sortType": 6,
        "includeLetAgreed": "false",
        "currencyCode": "GBP",
        "areaSizeUnit": "miles",
        "radius": 0.0,
        "furnishTypes": "furnished",
        # mustHave=parking omitted: parking checked client-side via _has_parking()
    }

    total_raw = 0
    total_strict = 0
    total_soft = 0
    total_result_count = 0
    seen_ids: set[str] = set()

    with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
        for i, borough in enumerate(SAMPLE_BOROUGHS):
            loc_id = get_location_id(borough)
            if not loc_id:
                print(f"  {borough}: no location ID, skipping")
                continue

            t0 = time.time()
            try:
                props, result_count = _fetch_raw_properties_for_location(
                    client, params, loc_id, max_pages=MAX_PAGES
                )
            except Exception as e:
                print(f"  {borough}: ERROR - {e}")
                continue

            elapsed = time.time() - t0
            total_result_count += result_count

            new_props = []
            for p in props:
                pid = str(p.get("id") or "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    new_props.append(p)

            total_raw += len(new_props)

            strict = [p for p in new_props if not _mandatory_reject_reasons(p)]
            soft = [p for p in new_props if _mandatory_reject_reasons(p) and _passes_soft_filters(p)]
            total_strict += len(strict)
            total_soft += len(soft)

            reject_counts: dict[str, int] = {}
            for p in new_props:
                for r in _mandatory_reject_reasons(p):
                    reject_counts[r] = reject_counts.get(r, 0) + 1

            print(
                f"  {borough:25s} loc={loc_id:20s}  "
                f"resultCount={result_count:5d}  raw={len(new_props):4d}  "
                f"strict={len(strict):3d}  soft={len(soft):3d}  "
                f"({elapsed:.1f}s)"
            )
            if reject_counts:
                top = sorted(reject_counts.items(), key=lambda x: -x[1])[:3]
                print(f"    reject reasons: {dict(top)}")

            # Pause between boroughs (matching production behaviour)
            if i < len(SAMPLE_BOROUGHS) - 1:
                time.sleep(5.0)

    print("=" * 60)
    print(f"SAMPLE TOTALS ({len(SAMPLE_BOROUGHS)} boroughs, {MAX_PAGES} pages each):")
    print(f"  Rightmove reported resultCount total : {total_result_count}")
    print(f"  Raw unique properties fetched        : {total_raw}")
    print(f"  Strict matches (all filters pass)    : {total_strict}")
    print(f"  Soft matches (1 minor deviation)     : {total_soft}")
    print()

    # Extrapolate to full London run
    full_borough_count = len(boroughs)
    scale = full_borough_count / len(SAMPLE_BOROUGHS)
    print(
        f"Estimated full London run ({full_borough_count} boroughs, {MAX_PAGES} pages):"
    )
    print(f"  ~{int(total_raw * scale)} raw unique  |  ~{int(total_strict * scale)} strict  |  ~{int(total_soft * scale)} soft")
    print(f"  (With MAX_PAGES_PER_LOCATION=42, up to ~{int(total_result_count / len(SAMPLE_BOROUGHS) * full_borough_count)} total listings available)")


if __name__ == "__main__":
    main()
