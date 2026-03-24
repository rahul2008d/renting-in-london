#!/usr/bin/env python3
"""Debug why a specific property (87714459) is not appearing in search results.

Usage: uv run python scripts/_debug_missing_property.py
"""
import json
import math
import sys
import time

sys.path.insert(0, ".")

import httpx

from tools.rightmove_search import (
    HEADERS,
    MANDATORY_MIN_BATHROOMS,
    PAGE_SIZE,
    RIGHTMOVE_REFERER,
    RIGHTMOVE_SEARCH_API,
    SOFT_MAX_PRICE,
    _collect_text_fields,
    _extract_properties_from_next_data_html,
    _fetch_properties_from_search_page,
    _has_parking,
    _is_furnished,
    _mandatory_reject_reasons,
    _passes_london_check,
    _passes_soft_filters,
    _safe_int,
)

TARGET_PROPERTY_ID = "87714459"
MAX_PAGES = 42


def _fetch_page(client: httpx.Client, params: dict) -> tuple[list[dict], int]:
    """Fetch one page via API, with find.html fallback. Returns (properties, result_count)."""
    page_props = None
    page_result_count = 0
    try:
        response = client.get(RIGHTMOVE_SEARCH_API, params=params)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" in content_type and "text/html" not in content_type:
            try:
                data = response.json()
                api_props = data.get("properties") if isinstance(data, dict) else None
                if isinstance(api_props, list):
                    page_props = [p for p in api_props if isinstance(p, dict)]
                    page_result_count = _safe_int(data.get("resultCount"), len(page_props))
            except json.JSONDecodeError:
                pass
    except httpx.HTTPStatusError:
        page_props = None
    if not page_props:
        response = client.get(RIGHTMOVE_REFERER, params=params)
        response.raise_for_status()
        page_props, page_result_count = _extract_properties_from_next_data_html(response.text)
        if not page_props:
            page_props, page_result_count = _fetch_properties_from_search_page(client, params)
    return page_props or [], page_result_count


def _search_for_property(raw_all: list[dict], prop_id: str) -> tuple[dict | None, int | None]:
    """Find property in list, return (prop, page_index) or (None, None)."""
    for idx, prop in enumerate(raw_all):
        pid = str(prop.get("id") or "")
        if pid == prop_id:
            return prop, None  # page_index not tracked in flat list
    return None, None


def main() -> None:
    base_params = {
        "channel": "RENT",
        "maxPrice": SOFT_MAX_PRICE,
        "minBedrooms": 2,
        "maxBedrooms": 4,
        "minBathrooms": MANDATORY_MIN_BATHROOMS,
        "numberOfPropertiesPerPage": PAGE_SIZE,
        "sortType": 6,
        "includeLetAgreed": "false",
        "currencyCode": "GBP",
        "areaSizeUnit": "miles",
        "radius": 0.0,
        "locationIdentifier": "REGION^87490",
        "furnishTypes": "furnished,partFurnished",
    }

    print("=" * 70)
    print(f"DEBUG: Missing property {TARGET_PROPERTY_ID}")
    print("Croham Road, South Croydon, CR2, £1900, 2 bed, 2 bath, part furnished, allocated parking")
    print("=" * 70)

    with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
        # ---- STEP 1: London-wide search, exact _run_search params, all pages ----
        print("\n[STEP 1] London-wide search (exact _run_search params, up to 42 pages)")
        raw_all: list[dict] = []
        result_count = 0
        found_page: int | None = None
        for page_idx in range(MAX_PAGES):
            page_params = dict(base_params)
            page_params["index"] = page_idx * PAGE_SIZE
            time.sleep(2.0)
            props, rc = _fetch_page(client, page_params)
            if page_idx == 0 and rc:
                result_count = rc
            for p in props or []:
                raw_all.append(p)
                if str(p.get("id") or "") == TARGET_PROPERTY_ID:
                    found_page = page_idx
            if not props or len(props) < PAGE_SIZE:
                break

        pages_fetched = (len(raw_all) + PAGE_SIZE - 1) // PAGE_SIZE if raw_all else 0
        print(f"  Pages fetched: {pages_fetched}, total raw props: {len(raw_all)}, resultCount: {result_count}")

        target_prop, _ = _search_for_property(raw_all, TARGET_PROPERTY_ID)
        if target_prop:
            print(f"  FOUND property {TARGET_PROPERTY_ID} on page {found_page}")
        else:
            print(f"  NOT FOUND in raw results ({len(raw_all)} properties)")

        # ---- STEP 2: If NOT found, try variants ----
        if not target_prop:
            print("\n[STEP 2] Trying search variants (property not in raw results)")
            variants = [
                ("No furnishTypes", {k: v for k, v in base_params.items() if k != "furnishTypes"}),
                ("furnishTypes=partFurnished only", {**base_params, "furnishTypes": "partFurnished"}),
                ("sortType=1 (lowest price)", {**base_params, "sortType": 1}),
            ]
            for label, params in variants:
                params = dict(params)
                params["index"] = 0
                time.sleep(2.0)
                props, rc = _fetch_page(client, params)
                count = len(props) if props else 0
                found = any(str(p.get("id") or "") == TARGET_PROPERTY_ID for p in (props or []))
                print(f"  {label}: resultCount={rc}, page0 props={count}, target_found={found}")
                if found:
                    target_prop = next(p for p in (props or []) if str(p.get("id") or "") == TARGET_PROPERTY_ID)
                    break

        # ---- STEP 3: If found, run through all filters ----
        if target_prop:
            print("\n[STEP 3] Filter diagnostics (property found in raw)")
            text_blob = _collect_text_fields(target_prop)
            print(f"  Text blob (first 200 chars): {repr(text_blob[:200])}...")

            passes_london = _passes_london_check(target_prop)
            print(f"  _passes_london_check(): {passes_london}")

            reject_reasons = _mandatory_reject_reasons(target_prop)
            print(f"  _mandatory_reject_reasons(): {reject_reasons}")

            passes_soft = _passes_soft_filters(target_prop)
            print(f"  _passes_soft_filters(): {passes_soft}")

            has_parking = _has_parking(text_blob)
            print(f"  _has_parking(text_blob): {has_parking}")

            is_furnished = _is_furnished(text_blob)
            print(f"  _is_furnished(text_blob): {is_furnished}")

        # ---- STEP 5: Croydon-specific search ----
        print("\n[STEP 5] Croydon-specific search (REGION^61312)")
        croydon_params = dict(base_params)
        croydon_params["locationIdentifier"] = "REGION^61312"
        croydon_params["index"] = 0
        time.sleep(2.0)
        props, rc = _fetch_page(client, croydon_params)
        count = len(props) if props else 0
        found_croydon = any(str(p.get("id") or "") == TARGET_PROPERTY_ID for p in (props or []))
        print(f"  resultCount: {rc}, page0 props: {count}, target_found: {found_croydon}")
        if found_croydon:
            print("  -> Property IS returned by Rightmove for Croydon search")
        else:
            print("  -> Property NOT in first page of Croydon results (may be on later pages)")

    print("\n" + "=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
