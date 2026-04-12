"""Smoke-test the Overpass API with a known London coordinate.

Verifies that each category query is reachable and returns data.
New category templates use `nwr` + `out center` so that polygon-mapped
features (parks, GP surgeries) fall back to centroid coordinates via the
`center` key — the `_parse_elements` function handles this transparently.

Usage:
    uv run python scripts/_test_overpass.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from tools.local_amenities import (
    HEADERS,
    RESTAURANT_QUERY,
    SUPERMARKET_QUERY,
    _run_query,
)

# ── Test coordinate ────────────────────────────────────────────────────────────
LAT = 51.5054  # Canary Wharf
LON = -0.0235

# ── Inline query templates for categories not yet in local_amenities.py ───────
# These use `nwr` (node + way + relation) so that shops/places mapped as
# polygon areas are included. `out center` makes Overpass return a centroid
# for each way/relation, which `_parse_elements` reads via element["center"].

PARK_QUERY = """
[out:json][timeout:25];
(
  nwr["leisure"="park"](around:{radius},{lat},{lon});
  nwr["leisure"="nature_reserve"](around:{radius},{lat},{lon});
);
out center;
""".strip()

GP_SURGERY_QUERY = """
[out:json][timeout:25];
(
  nwr["amenity"="doctors"](around:{radius},{lat},{lon});
  nwr["healthcare"="doctor"](around:{radius},{lat},{lon});
);
out center;
""".strip()

PHARMACY_QUERY = """
[out:json][timeout:25];
(
  nwr["amenity"="pharmacy"](around:{radius},{lat},{lon});
);
out center;
""".strip()

CAFE_QUERY = """
[out:json][timeout:25];
(
  nwr["amenity"="cafe"](around:{radius},{lat},{lon});
);
out center;
""".strip()

STATION_QUERY = """
[out:json][timeout:25];
(
  nwr["railway"="station"](around:{radius},{lat},{lon});
  nwr["station"="subway"](around:{radius},{lat},{lon});
);
out center;
""".strip()

# ── Category definitions: (label, query_template, radius_metres) ──────────────
CATEGORIES: list[tuple[str, str, int]] = [
    ("Supermarkets", SUPERMARKET_QUERY, 1000),
    ("Restaurants", RESTAURANT_QUERY, 1000),
    ("Parks", PARK_QUERY, 500),
    ("GP surgeries", GP_SURGERY_QUERY, 1000),
    ("Pharmacies", PHARMACY_QUERY, 500),
    ("Cafes", CAFE_QUERY, 500),
    ("Train/tube stations", STATION_QUERY, 1000),
]


def _fmt_label(label: str, radius: int) -> str:
    return f"{label} (within {radius}m)"


def main() -> None:
    print(f"Overpass API smoke-test — Canary Wharf ({LAT}, {LON})")
    print("=" * 60)

    passed: list[str] = []
    failed: list[str] = []

    with httpx.Client(timeout=40.0, headers=HEADERS, follow_redirects=True) as client:
        for i, (label, query_template, radius) in enumerate(CATEGORIES):
            if i > 0:
                time.sleep(2.0)

            display = _fmt_label(label, radius)
            print(f"\n[{display}]")
            try:
                results = _run_query(
                    client=client,
                    query_template=query_template,
                    latitude=LAT,
                    longitude=LON,
                    radius_metres=radius,
                )
                count = len(results)
                print(f"  Results : {count}")
                if results:
                    nearest = results[0]
                    print(f"  Nearest : {nearest['name']} — {nearest['distance_m']}m")
                else:
                    print(f"  Nearest : (none in radius)")
                print(f"  Status  : OK")
                passed.append(display)
            except httpx.TimeoutException:
                print(f"  Status  : FAILED — request timed out")
                failed.append(display)
            except httpx.HTTPStatusError as exc:
                print(f"  Status  : FAILED — HTTP {exc.response.status_code}")
                failed.append(display)
            except Exception as exc:
                print(f"  Status  : FAILED — {exc.__class__.__name__}: {exc}")
                failed.append(display)

    print("\n" + "=" * 60)
    print(f"SUMMARY  {len(passed)} passed / {len(failed)} failed / {len(CATEGORIES)} total")
    for label in passed:
        print(f"  PASS  {label}")
    for label in failed:
        print(f"  FAIL  {label}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
