import sys; sys.path.insert(0, ".")
from tools.rightmove_search import _is_furnished
from data.london_areas import get_london_borough_areas, get_location_id

cases = [
    ("furnished flat with parking", True),
    ("unfurnished flat", False),
    ("furnished or unfurnished", True),
    ("furnished / unfurnished", True),
    ("available unfurnished", False),
    ("part-furnished", True),
]
for text, expected in cases:
    result = _is_furnished(text)
    status = "OK" if result == expected else "FAIL"
    print(f"{status}: {text!r} -> {result} (expected {expected})")

areas = get_london_borough_areas()
loc_ids = [get_location_id(a) for a in areas]
dup_ids = [lid for lid in set(loc_ids) if loc_ids.count(lid) > 1]
print(f"\nget_london_borough_areas(): {len(areas)} areas, duplicate REGION IDs: {dup_ids}")
