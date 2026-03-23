from __future__ import annotations

import json
import unittest
from unittest import mock

from tools import property_details


class _DummyResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _DummyClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        return self._response


class TestPropertyDetailsTool(unittest.TestCase):
    def test_requires_property_id(self) -> None:
        payload = json.loads(property_details.get_property_details(""))
        self.assertEqual(payload["error"], "property_id is required.")

    def test_handles_404(self) -> None:
        response = _DummyResponse(status_code=404)
        with mock.patch.object(property_details.httpx, "Client", return_value=_DummyClient(response)), \
             mock.patch("time.sleep"):
            payload = json.loads(property_details.get_property_details("123"))
        self.assertIn("not found", payload["error"].lower())

    def test_parses_page_model_payload(self) -> None:
        page_model = {
            "propertyData": {
                "address": {"displayAddress": "Test Street, London"},
                "prices": {"primaryPrice": "GBP 2200 pcm"},
                "propertySubType": "Flat",
                "bedrooms": 2,
                "bathrooms": 2,
                "text": {"description": "Great home"},
                "keyFeatures": ["Furnished", "Parking"],
                "lettings": {
                    "furnishType": "Furnished",
                    "minimumTermOfTenancyDescription": "12 months",
                },
                "customerName": "Agent X",
                "branchName": "Branch Y",
                "contactInfo": {"telephoneNumbers": {"localNumber": "020000000"}},
                "location": {"latitude": 51.5, "longitude": -0.1},
                "nearestStations": [{"name": "Station A", "distance": 0.2}],
                "epc": {"currentEnergyRating": "B"},
                "images": [{"id": 1}, {"id": 2}],
            }
        }
        html = f"<html><script>window.PAGE_MODEL = {json.dumps(page_model)};</script></html>"
        response = _DummyResponse(status_code=200, text=html)

        with mock.patch.object(property_details.httpx, "Client", return_value=_DummyClient(response)), \
             mock.patch("time.sleep"):
            payload = json.loads(property_details.get_property_details("123456"))

        self.assertEqual(payload["property_id"], "123456")
        self.assertEqual(payload["bedrooms"], 2)
        self.assertEqual(payload["epc_rating"], "B")
        self.assertEqual(payload["image_count"], 2)
        self.assertIn("informative_summary", payload)


if __name__ == "__main__":
    unittest.main()
