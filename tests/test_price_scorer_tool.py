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
        ranked = payload["ranked_properties"]
        self.assertEqual(len(ranked), 2)
        self.assertGreaterEqual(ranked[0]["total_score"], ranked[1]["total_score"])
        self.assertIn("scores", ranked[0])

    def test_invalid_priority_falls_back_to_balanced(self) -> None:
        payload = json.loads(score_properties(json.dumps({"properties": []}), priorities="bad-priority"))
        self.assertEqual(payload["priorities"], "balanced")


if __name__ == "__main__":
    unittest.main()
