#!/usr/bin/env python3
import sys; sys.path.insert(0, ".")
import httpx
from tools.rightmove_search import (
    RIGHTMOVE_REFERER, HEADERS, SOFT_MAX_PRICE,
    _extract_properties_from_next_data_html,
    _is_london_listing, _is_in_london_bounds, _mandatory_reject_reasons,
)

with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
    for borough, loc_id in [("Hackney", "REGION^61342"), ("Southwark", "REGION^61456")]:
        r = client.get(RIGHTMOVE_REFERER, params={
            "locationIdentifier": loc_id, "minBedrooms": 2, "maxBedrooms": 4,
            "maxPrice": SOFT_MAX_PRICE, "channel": "RENT", "index": 0,
        })
        props, rc = _extract_properties_from_next_data_html(r.text)
        print(f"\n{borough}: {len(props) if props else 0} props, resultCount={rc}")
        if not props:
            continue
        pass_london = sum(1 for p in props if _is_london_listing(p))
        pass_bounds = sum(1 for p in props if _is_in_london_bounds(p))
        pass_both = sum(1 for p in props if _is_london_listing(p) and _is_in_london_bounds(p))
        print(f"  is_london_listing pass: {pass_london}/{len(props)}")
        print(f"  is_in_london_bounds pass: {pass_bounds}/{len(props)}")
        print(f"  Both pass (added to raw): {pass_both}/{len(props)}")

        # Show sample addresses and location for those failing
        failed = [p for p in props if not (_is_london_listing(p) and _is_in_london_bounds(p))]
        if failed:
            print(f"  Failing samples:")
            for p in failed[:3]:
                loc = p.get("location") or {}
                addr = p.get("displayAddress","")
                print(f"    addr={addr!r}  lat={loc.get('latitude')}  lon={loc.get('longitude')}  london={_is_london_listing(p)}  bounds={_is_in_london_bounds(p)}")
        passing = [p for p in props if _is_london_listing(p) and _is_in_london_bounds(p)]
        if passing:
            p = passing[0]
            reasons = _mandatory_reject_reasons(p)
            print(f"  First passing prop: addr={p.get('displayAddress')!r}  price={p.get('price',{}).get('amount')}  beds={p.get('bedrooms')}  baths={p.get('bathrooms')}  reject_reasons={reasons}")
