#!/usr/bin/env python3
"""Live end-to-end property count for London-wide search with all improvements."""
import sys, time; sys.path.insert(0, ".")
import math
import httpx
from tools.rightmove_search import (
    RIGHTMOVE_REFERER, HEADERS, SOFT_MAX_PRICE, PAGE_SIZE,
    _extract_properties_from_next_data_html, _is_london_listing, _is_in_london_bounds,
    _mandatory_reject_reasons, _passes_soft_filters,
)

params = {
    "locationIdentifier": "REGION^87490",
    "channel": "RENT",
    "maxPrice": SOFT_MAX_PRICE,
    "minBedrooms": 2,
    "maxBedrooms": 4,
    "minBathrooms": 2,
    "furnishTypes": "furnished",
    # mustHave=parking omitted: parking checked client-side via _has_parking()
    "sortType": 6,
    "currencyCode": "GBP",
    "areaSizeUnit": "miles",
    "radius": 0.0,
    "numberOfPropertiesPerPage": PAGE_SIZE,
    "includeLetAgreed": "false",
}

raw_all: list[dict] = []
seen_ids: set[str] = set()
result_count = 0
pages_to_fetch = 42  # Will be updated from first-page resultCount

t_start = time.time()
with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
    page_index = 0
    while page_index < pages_to_fetch:
        p = {**params, "index": page_index * PAGE_SIZE}
        r = client.get(RIGHTMOVE_REFERER, params=p)
        props, rc = _extract_properties_from_next_data_html(r.text)

        if props and rc and rc > result_count:
            result_count = rc
            pages_to_fetch = min(42, math.ceil(result_count / PAGE_SIZE))
            print(f"Page {page_index}: resultCount={result_count} → need {pages_to_fetch} pages")

        if not props:
            print(f"Page {page_index}: no properties returned, stopping")
            break

        new = [x for x in props if str(x.get("id","")) not in seen_ids]
        for x in new:
            seen_ids.add(str(x.get("id","")))
        raw_all.extend(new)

        if page_index > 0 and page_index % 3 == 0:
            print(f"  Page {page_index}: +{len(new)} new props (cumulative raw={len(raw_all)})")

        if len(props) < PAGE_SIZE:
            print(f"  Short page ({len(props)} < {PAGE_SIZE}), stopping")
            break

        if page_index < pages_to_fetch - 1:
            time.sleep(1.5)
        page_index += 1

elapsed = time.time() - t_start

in_london = [p for p in raw_all if _is_london_listing(p) and _is_in_london_bounds(p)]
strict = [p for p in in_london if not _mandatory_reject_reasons(p)]
soft = [p for p in in_london if _mandatory_reject_reasons(p) and _passes_soft_filters(p)]

reject_totals: dict[str, int] = {}
for p in in_london:
    for r in _mandatory_reject_reasons(p):
        reject_totals[r] = reject_totals.get(r, 0) + 1

print(f"\n{'='*60}")
print(f"LONDON-WIDE LIVE RESULTS ({elapsed:.0f}s):")
print(f"  Rightmove total (resultCount)  : {result_count}")
print(f"  Pages fetched                  : {page_index + 1}")
print(f"  Raw unique properties          : {len(raw_all)}")
print(f"  In-London (geo-filtered)       : {len(in_london)}")
print(f"  Strict matches (top_picks)     : {len(strict)}")
print(f"  Soft matches (with_trade_offs) : {len(soft)}")
print(f"  Reject reason breakdown        : {dict(sorted(reject_totals.items(), key=lambda x:-x[1]))}")
