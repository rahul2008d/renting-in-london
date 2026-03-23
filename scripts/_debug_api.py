#!/usr/bin/env python3
import sys; sys.path.insert(0, ".")
import httpx
from tools.rightmove_search import (
    RIGHTMOVE_SEARCH_API, RIGHTMOVE_REFERER, HEADERS, SOFT_MAX_PRICE,
    _extract_properties_from_next_data_html,
)

base = {
    "channel": "RENT", "maxPrice": SOFT_MAX_PRICE, "minBedrooms": 2, "maxBedrooms": 4,
    "minBathrooms": 2, "numberOfPropertiesPerPage": 24, "sortType": 6,
    "includeLetAgreed": "false", "currencyCode": "GBP", "areaSizeUnit": "miles",
    "radius": 0.0, "furnishTypes": "furnished", "mustHave": "parking", "index": 0,
}

tests = [
    ("Hackney API",       RIGHTMOVE_SEARCH_API, {**base, "locationIdentifier": "REGION^61342"}),
    ("Hackney find.html minimal", RIGHTMOVE_REFERER,  {"locationIdentifier": "REGION^61342", "minBedrooms": 2, "maxBedrooms": 4, "maxPrice": SOFT_MAX_PRICE, "channel": "RENT"}),
    ("Hackney find.html full",    RIGHTMOVE_REFERER,  {**base, "locationIdentifier": "REGION^61342"}),
    ("London API",        RIGHTMOVE_SEARCH_API, {**base, "locationIdentifier": "REGION^87490"}),
    ("London find.html minimal",  RIGHTMOVE_REFERER,  {"locationIdentifier": "REGION^87490", "minBedrooms": 2, "maxBedrooms": 4, "maxPrice": SOFT_MAX_PRICE, "channel": "RENT"}),
    ("London find.html full",     RIGHTMOVE_REFERER,  {**base, "locationIdentifier": "REGION^87490"}),
]

with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
    for label, url, params in tests:
        r = client.get(url, params=params)
        ct = r.headers.get("content-type", "")
        props, rc = None, None
        if "application/json" in ct and "text/html" not in ct:
            try:
                d = r.json()
                props = d.get("properties") or []
                rc = d.get("resultCount", 0)
            except Exception:
                pass
        if props is None:
            props, rc = _extract_properties_from_next_data_html(r.text)
        print(f"{label:35s}: status={r.status_code} ct={ct[:30]:30s} props={len(props) if props else 0:4d} resultCount={rc}")
