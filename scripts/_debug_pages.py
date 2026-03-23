#!/usr/bin/env python3
"""Test pagination: how many pages does London-wide fetch return with minimal vs full params?"""
import sys; sys.path.insert(0, ".")
import httpx
from tools.rightmove_search import (
    RIGHTMOVE_REFERER, HEADERS, SOFT_MAX_PRICE, PAGE_SIZE,
    _extract_properties_from_next_data_html, _is_london_listing, _is_in_london_bounds,
    _mandatory_reject_reasons, _passes_soft_filters,
)

base_minimal = {"locationIdentifier": "REGION^87490", "minBedrooms": 2, "maxBedrooms": 4, "maxPrice": SOFT_MAX_PRICE, "channel": "RENT", "sortType": 6}
base_full = {**base_minimal, "minBathrooms": 2, "furnishTypes": "furnished", "mustHave": "parking", "currencyCode": "GBP", "areaSizeUnit": "miles", "radius": 0.0}

with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
    for label, params in [("London minimal", base_minimal), ("London full", base_full)]:
        total_props = []
        seen_ids = set()
        for page in range(5):  # test up to 5 pages
            p = {**params, "index": page * PAGE_SIZE}
            r = client.get(RIGHTMOVE_REFERER, params=p)
            props, rc = _extract_properties_from_next_data_html(r.text)
            if not props:
                break
            new = [x for x in props if str(x.get("id","")) not in seen_ids and (seen_ids.add(str(x.get("id",""))) or True)]
            total_props.extend(new)
            if page == 0:
                print(f"\n{label}: page0 props={len(props)}, resultCount={rc}")
            else:
                print(f"  page{page}: props={len(props)}")
            if len(props) < PAGE_SIZE:
                print(f"  Short page ({len(props)}<{PAGE_SIZE}), stopping")
                break
        in_london = [p for p in total_props if _is_london_listing(p) and _is_in_london_bounds(p)]
        strict = [p for p in in_london if not _mandatory_reject_reasons(p)]
        soft = [p for p in in_london if _mandatory_reject_reasons(p) and _passes_soft_filters(p)]
        print(f"  5-page total: raw={len(total_props)}, in_london={len(in_london)}, strict={len(strict)}, soft={len(soft)}")
