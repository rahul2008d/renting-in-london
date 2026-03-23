from __future__ import annotations

import json
import unittest

from tools.decision_ranker import rank_property_decisions


class TestDecisionRankerTool(unittest.TestCase):
    def test_requires_properties_json(self) -> None:
        payload = json.loads(rank_property_decisions(""))
        self.assertEqual(payload["error"], "properties_json is required.")

    def test_rejects_invalid_json(self) -> None:
        payload = json.loads(rank_property_decisions("{bad"))
        self.assertEqual(payload["error"], "properties_json is not valid JSON.")

    def test_returns_empty_structure_for_no_properties(self) -> None:
        payload = json.loads(rank_property_decisions(json.dumps({"properties": []})))
        self.assertEqual(payload["total_input_properties"], 0)
        self.assertEqual(payload["strong_matches"], [])
        self.assertEqual(payload["maybe_matches"], [])
        self.assertEqual(payload["rejects"], [])

    def test_classifies_and_summarizes_with_reject_toggle(self) -> None:
        properties = {
            "properties": [
                {
                    "id": "1",
                    "address": "A",
                    "url": "u1",
                    "price_pcm": 1800,
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "distance_miles": 2.0,
                    "summary": "furnished with parking",
                    "key_features": ["Allocated parking", "Furnished", "Balcony"],
                    "mandatory_checks": {
                        "price_ok": True,
                        "bedrooms_ok": True,
                        "bathrooms_ok": True,
                        "distance_ok": True,
                        "parking_ok": True,
                        "furnished_ok": True,
                        "excluded_type_ok": True,
                    },
                },
                {
                    "id": "2",
                    "address": "B",
                    "url": "u2",
                    "price_pcm": 2200,
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "distance_miles": 4.0,
                    "summary": "compact but furnished with parking",
                    "key_features": ["Parking", "Furnished"],
                    "mandatory_checks": {
                        "price_ok": True,
                        "bedrooms_ok": True,
                        "bathrooms_ok": True,
                        "distance_ok": True,
                        "parking_ok": True,
                        "furnished_ok": True,
                        "excluded_type_ok": True,
                    },
                },
                {
                    "id": "3",
                    "address": "C",
                    "url": "u3",
                    "price_pcm": 2600,
                    "bedrooms": 1,
                    "bathrooms": 1,
                    "distance_miles": 8.0,
                    "summary": "unfurnished no parking",
                    "key_features": ["Needs work"],
                    "mandatory_checks": {
                        "price_ok": False,
                        "bedrooms_ok": False,
                        "bathrooms_ok": False,
                        "distance_ok": False,
                        "parking_ok": False,
                        "furnished_ok": False,
                        "excluded_type_ok": True,
                    },
                },
            ]
        }

        compact = json.loads(rank_property_decisions(json.dumps(properties)))
        self.assertGreaterEqual(compact["summary"]["reject_count"], 1)
        self.assertEqual(len(compact["rejects"]), 0)
        non_reject_count = compact["summary"]["strong_match_count"] + compact["summary"]["maybe_count"]
        self.assertGreaterEqual(non_reject_count, 1)

        full = json.loads(
            rank_property_decisions(
                json.dumps(properties),
                include_reject_items=True,
                max_per_bucket=10,
            )
        )
        self.assertEqual(len(full["rejects"]), full["summary"]["reject_count"])
        reject_ids = {item.get("id") for item in full["rejects"]}
        self.assertIn("3", reject_ids)

    def test_accepts_search_london_rentals_format(self) -> None:
        """Decision ranker should accept top_picks + with_trade_offs from search_london_rentals."""
        payload = {
            "top_picks": [
                {
                    "id": "1",
                    "address": "A",
                    "price_pcm": 2000,
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "distance_miles": 3.0,
                    "summary": "furnished parking",
                    "key_features": ["Parking", "Furnished"],
                    "mandatory_checks": {
                        "price_ok": True,
                        "bedrooms_ok": True,
                        "bathrooms_ok": True,
                        "distance_ok": True,
                        "parking_ok": True,
                        "furnished_ok": True,
                        "excluded_type_ok": True,
                    },
                },
            ],
            "with_trade_offs": [
                {
                    "id": "2",
                    "address": "B",
                    "price_pcm": 2400,
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "distance_miles": 4.0,
                    "summary": "furnished parking",
                    "key_features": ["Parking", "Furnished"],
                    "trade_off_reasons": ["Slightly over budget (£2400 pcm vs £2300 max)"],
                },
            ],
        }
        result = json.loads(rank_property_decisions(json.dumps(payload)))
        self.assertEqual(result["total_input_properties"], 2)
        self.assertIn("strong_matches", result)
        self.assertIn("maybe_matches", result)


if __name__ == "__main__":
    unittest.main()
