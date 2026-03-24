from __future__ import annotations

import json
import unittest

from tools.price_scorer import score_properties


class TestPriceScorerTool(unittest.TestCase):
    def test_requires_properties_json(self) -> None:
        payload = json.loads(score_properties(""))
        self.assertEqual(payload["error"], "properties_json is required.")

    def test_rejects_invalid_json(self) -> None:
        payload = json.loads(score_properties("{bad"))
        self.assertEqual(payload["error"], "properties_json is not valid JSON.")

    def test_returns_empty_result_for_no_properties(self) -> None:
        payload = json.loads(score_properties(json.dumps({"properties": []})))
        self.assertEqual(payload["total_properties"], 0)
        self.assertEqual(payload["ranked_properties"], [])
        summary = payload["summary"]
        self.assertEqual(summary["total_scored"], 0)
        self.assertEqual(summary["from_top_picks"], 0)
        self.assertEqual(summary["from_trade_offs"], 0)

    def test_scores_and_ranks_properties(self) -> None:
        src = {
            "properties": [
                {
                    "id": "p1",
                    "url": "u1",
                    "address": "Hackney London",
                    "price_pcm": 1800,
                    "bedrooms": 2,
                    "property_type": "flat",
                    "latitude": 51.54,
                    "longitude": -0.07,
                },
                {
                    "id": "p2",
                    "url": "u2",
                    "address": "Hackney London",
                    "price_pcm": 2200,
                    "bedrooms": 2,
                    "property_type": "flat",
                    "latitude": 51.54,
                    "longitude": -0.07,
                },
            ]
        }

        payload = json.loads(
            score_properties(
                json.dumps(src),
                workplace_lat=51.515,
                workplace_lon=-0.08,
                priorities="budget",
            )
        )

        self.assertEqual(payload["priorities"], "budget")
        self.assertEqual(payload["total_properties"], 2)
        self.assertIn("summary", payload)
        ranked = payload["ranked_properties"]
        self.assertEqual(len(ranked), 2)
        self.assertGreaterEqual(ranked[0]["total_score"], ranked[1]["total_score"])
        self.assertIn("scores", ranked[0])
        self.assertIn("parking_status", ranked[0])
        self.assertIn("amenity_tags", ranked[0])
        self.assertEqual(payload["summary"]["total_scored"], 2)

    def test_search_shape_tags_source_tier_and_summary_counts(self) -> None:
        src = {
            "top_picks": [
                {
                    "id": "a1",
                    "url": "u1",
                    "address": "Hackney London",
                    "price_pcm": 1800,
                    "bedrooms": 2,
                    "property_type": "flat",
                    "latitude": 51.54,
                    "longitude": -0.07,
                    "parking_status": "confirmed",
                },
            ],
            "with_trade_offs": [
                {
                    "id": "b1",
                    "url": "u2",
                    "address": "Hackney London",
                    "price_pcm": 2200,
                    "bedrooms": 2,
                    "property_type": "flat",
                    "latitude": 51.54,
                    "longitude": -0.07,
                    "parking_status": "unconfirmed",
                    "trade_off_reasons": ["Small kitchen"],
                },
            ],
        }
        payload = json.loads(
            score_properties(
                json.dumps(src),
                workplace_lat=51.515,
                workplace_lon=-0.08,
                priorities="balanced",
            )
        )
        by_id = {r["id"]: r for r in payload["ranked_properties"]}
        self.assertEqual(by_id["a1"]["source_tier"], "top_pick")
        self.assertEqual(by_id["b1"]["source_tier"], "trade_off")
        self.assertEqual(by_id["b1"]["trade_off_reasons"], ["Small kitchen"])
        s = payload["summary"]
        self.assertEqual(s["from_top_picks"], 1)
        self.assertEqual(s["from_trade_offs"], 1)
        self.assertEqual(s["total_scored"], 2)

    def test_invalid_priority_falls_back_to_balanced(self) -> None:
        payload = json.loads(score_properties(json.dumps({"properties": []}), priorities="bad-priority"))
        self.assertEqual(payload["priorities"], "balanced")


if __name__ == "__main__":
    unittest.main()
