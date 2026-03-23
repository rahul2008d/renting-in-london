from __future__ import annotations

import json
import unittest
from unittest import mock

import httpx

from tools import local_amenities


class _DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestLocalAmenitiesTool(unittest.TestCase):
    def test_rejects_invalid_amenity_type(self) -> None:
        payload = json.loads(local_amenities.find_nearby_amenities(51.5, -0.1, amenity_type="gym"))
        self.assertIn("error", payload)
        self.assertIn("Invalid amenity_type", payload["error"])

    def test_all_categories_return_counts_and_results(self) -> None:
        def fake_run_query(client, query_template, latitude, longitude, radius_metres):
            if query_template == local_amenities.INDIAN_GROCERY_QUERY:
                return [{"name": "A", "distance_m": 100}]
            if query_template == local_amenities.RESTAURANT_QUERY:
                return [{"name": "B", "distance_m": 110}, {"name": "C", "distance_m": 150}]
            return []

        with mock.patch.object(local_amenities.httpx, "Client", return_value=_DummyClient()):
            with mock.patch.object(local_amenities, "_run_query", side_effect=fake_run_query):
                payload = json.loads(local_amenities.find_nearby_amenities(51.5, -0.1, amenity_type="all", radius_metres=50))

        # Radius should be clamped to minimum 100.
        self.assertEqual(payload["radius_metres"], 100)
        self.assertEqual(payload["result_counts"]["indian_grocery"], 1)
        self.assertEqual(payload["result_counts"]["restaurant"], 2)
        self.assertIn("results", payload)
        self.assertIn("supermarket", payload["results"])

    def test_network_error_is_reported(self) -> None:
        request = httpx.Request("POST", local_amenities.OVERPASS_URL)
        with mock.patch.object(local_amenities.httpx, "Client", return_value=_DummyClient()):
            with mock.patch.object(local_amenities, "_run_query", side_effect=httpx.RequestError("boom", request=request)):
                payload = json.loads(local_amenities.find_nearby_amenities(51.5, -0.1, amenity_type="restaurant"))
        self.assertIn("error", payload)
        self.assertIn("Network error", payload["error"])


if __name__ == "__main__":
    unittest.main()
