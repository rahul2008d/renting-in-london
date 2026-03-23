from __future__ import annotations

import json
import unittest
from unittest import mock

from tools import rightmove_search


class _DummyResponse:
    def __init__(self, *, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_data is None:
            raise json.JSONDecodeError("bad", "", 0)
        return self._json_data


class _DummyClient:
    def __init__(self, get_side_effect):
        self._get_side_effect = get_side_effect

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None):
        return self._get_side_effect(url, params)


def _base_property(property_id: str, *, price: int, bedrooms: int, bathrooms: int, distance: float, summary: str):
    return {
        "id": property_id,
        "price": {
            "amount": price,
            "displayAmount": f"GBP {price} pcm",
            "displayPrices": [{"displayPrice": f"GBP {price} pcm"}],
        },
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "distance": distance,
        "displayAddress": "Hackney, London E8",
        "propertySubType": "Flat",
        "propertyTypeFullDescription": "Flat",
        "displaySize": "700 sq ft",
        "displayStatus": "Available",
        "students": False,
        "formattedDistance": f"{distance} miles",
        "location": {"latitude": 51.54, "longitude": -0.07},
        "customerName": "Agent",
        "formattedBranchName": "Branch",
        "firstVisibleDate": "2026-01-01",
        "listingUpdate": {"listingUpdateReason": "new", "listingUpdateDate": "2026-01-01"},
        "isRecent": True,
        "letAvailableDate": "now",
        "keyFeatures": ["Furnished", "Allocated parking"],
        "propertyImages": {"images": [{"srcUrl": "img1"}]},
        "summary": summary,
        "keywords": ["parking", "furnished"],
    }


class TestRightmoveSearchTool(unittest.TestCase):
    def test_returns_empty_when_no_results(self) -> None:
        """When search returns no properties, output has empty top_picks and with_trade_offs."""
        with mock.patch.object(
            rightmove_search,
            "_run_search",
            return_value=([], [], [], [], ["London"], {}),
        ):
            payload = json.loads(rightmove_search.search_london_rentals())
        self.assertNotIn("error", payload)
        self.assertEqual(payload["top_picks"], [])
        self.assertEqual(payload["with_trade_offs"], [])

    def test_handles_rate_limit(self) -> None:
        def raise_429(*args, **kwargs):
            resp = rightmove_search.httpx.Response(429, request=rightmove_search.httpx.Request("GET", "http://x"))
            raise rightmove_search.httpx.HTTPStatusError("429", request=resp.request, response=resp)

        with mock.patch.object(rightmove_search, "_run_search", side_effect=raise_429):
            payload = json.loads(rightmove_search.search_london_rentals())
        self.assertIn("rate-limited", payload["error"])

    def test_filters_and_returns_top_picks_and_trade_offs(self) -> None:
        strict_prop = _base_property(
            "1001",
            price=2200,
            bedrooms=2,
            bathrooms=2,
            distance=2.0,
            summary="A furnished flat with parking",
        )
        soft_prop = _base_property(
            "1002",
            price=2400,
            bedrooms=2,
            bathrooms=1,
            distance=4.0,
            summary="Furnished flat with parking",
        )
        failing = _base_property(
            "1003",
            price=2600,
            bedrooms=1,
            bathrooms=1,
            distance=7.0,
            summary="Unfurnished property no parking",
        )
        failing["keywords"] = ["unfurnished"]

        response_payload = {"properties": [strict_prop, soft_prop, failing], "resultCount": 3}

        def mock_get(url, params=None):
            if rightmove_search.RIGHTMOVE_SEARCH_API in str(url):
                return _DummyResponse(json_data=response_payload, headers={"content-type": "application/json"})
            return _DummyResponse(json_data={}, headers={"content-type": "application/json"})

        with mock.patch("time.sleep"):
            with mock.patch.object(rightmove_search.httpx, "Client", return_value=_DummyClient(mock_get)):
                with mock.patch.object(rightmove_search, "get_location_id", side_effect=lambda a: f"REGION^{hash(a) % 100000}"):
                    payload = json.loads(rightmove_search.search_london_rentals(max_top_picks=5, max_trade_offs=5))
        self.assertNotIn("error", payload)
        self.assertIn("top_picks", payload)
        self.assertIn("with_trade_offs", payload)
        self.assertIn("properties", payload)
        self.assertIn("filter_diagnostics", payload)
        self.assertIn("constraint_impact_if_relaxed", payload["filter_diagnostics"])
        self.assertIn("areas_queried", payload)
        self.assertGreater(len(payload["areas_queried"]), 0)

    def test_extracted_properties_have_zone_and_required_fields(self) -> None:
        """Top picks and trade-offs include zone (derived from address) and required fields."""
        strict_prop = _base_property(
            "2001",
            price=2100,
            bedrooms=2,
            bathrooms=2,
            distance=3.0,
            summary="Furnished with allocated parking",
        )
        strict_prop["displayAddress"] = "Clapham High Street, London SW4 7AB"

        with mock.patch.object(
            rightmove_search,
            "_run_search",
            return_value=(
                [strict_prop],
                [strict_prop],
                [],
                [],
                ["London"],
                {},
            ),
        ):
            payload = json.loads(rightmove_search.search_london_rentals(max_top_picks=5))

        self.assertNotIn("error", payload)
        picks = payload.get("top_picks", [])
        self.assertGreater(len(picks), 0)
        first = picks[0]
        self.assertIn("zone", first)
        self.assertIsInstance(first["zone"], int)
        self.assertIn("address", first)
        self.assertIn("price_pcm", first)


if __name__ == "__main__":
    unittest.main()
