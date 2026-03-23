from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tools import commute_time


class _DummyResponse:
    def __init__(self, *, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
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


class TestCommuteTimeTool(unittest.TestCase):
    def setUp(self) -> None:
        commute_time.COMMUTE_CACHE.clear()
        commute_time.SERPAPI_DISABLED_UNTIL = 0.0

    def test_requires_destination(self) -> None:
        payload = json.loads(commute_time.calculate_commute(51.5, -0.1, ""))
        self.assertEqual(payload["error"], "to_location is required.")

    def test_uses_cache_for_identical_request(self) -> None:
        fake_payload = {"provider": "serpapi_google_maps", "journey_options": [{"total_duration_minutes": 30}]}
        with mock.patch.object(commute_time.httpx, "Client", return_value=_DummyClient(lambda u, p: _DummyResponse())):
            with mock.patch.object(commute_time, "_try_serpapi_google_maps_commute", return_value=fake_payload) as serp:
                first = commute_time.calculate_commute(51.5, -0.1, "22 Bishopsgate")
                second = commute_time.calculate_commute(51.5, -0.1, "22 Bishopsgate")
        self.assertEqual(first, second)
        self.assertEqual(serp.call_count, 1)

    def test_disable_serpapi_uses_google_fallback(self) -> None:
        os.environ["DISABLE_SERPAPI"] = "true"
        self.addCleanup(lambda: os.environ.pop("DISABLE_SERPAPI", None))

        google_payload = {"provider": "google_maps", "journey_options": [{"total_duration_minutes": 40}]}
        with mock.patch.object(commute_time.httpx, "Client", return_value=_DummyClient(lambda u, p: _DummyResponse())):
            with mock.patch.object(commute_time, "_try_serpapi_google_maps_commute", return_value=None) as serp:
                with mock.patch.object(commute_time, "_try_google_commute", return_value=google_payload) as google:
                    payload = json.loads(commute_time.calculate_commute(51.5, -0.1, "22 Bishopsgate"))
        self.assertEqual(payload["provider"], "google_maps")
        self.assertEqual(serp.call_count, 1)
        self.assertEqual(google.call_count, 1)

    def test_tfl_fallback_path_returns_tfl_payload(self) -> None:
        journeys = {
            "journeys": [
                {"duration": 32, "legs": [{"mode": {"name": "walking"}, "duration": 5}]},
                {"duration": 36, "legs": [{"mode": {"name": "tube"}, "duration": 20}]},
            ]
        }

        def get_side_effect(url, params):
            if "JourneyResults" in url:
                return _DummyResponse(json_data=journeys)
            return _DummyResponse(json_data={"places": [{"lat": 51.5, "lon": -0.08, "commonName": "Office"}]})

        with mock.patch.object(commute_time.httpx, "Client", return_value=_DummyClient(get_side_effect)):
            with mock.patch.object(commute_time, "_try_serpapi_google_maps_commute", return_value=None):
                with mock.patch.object(commute_time, "_try_google_commute", return_value=None):
                    payload = json.loads(commute_time.calculate_commute(51.53, -0.09, "22 Bishopsgate"))

        self.assertEqual(payload["provider"], "tfl")
        self.assertEqual(payload["total_options"], 2)
        self.assertEqual(payload["journey_options"][0]["total_duration_minutes"], 32)


if __name__ == "__main__":
    unittest.main()
