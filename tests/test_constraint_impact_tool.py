from __future__ import annotations

import json
import unittest

from tools.constraint_impact import analyze_constraint_impact


class TestConstraintImpactTool(unittest.TestCase):
    def test_requires_json_payload(self) -> None:
        payload = json.loads(analyze_constraint_impact(""))
        self.assertEqual(payload["error"], "search_results_json is required.")

    def test_rejects_invalid_json(self) -> None:
        payload = json.loads(analyze_constraint_impact("not-json"))
        self.assertEqual(payload["error"], "search_results_json is not valid JSON.")

    def test_requires_filter_diagnostics(self) -> None:
        payload = json.loads(analyze_constraint_impact(json.dumps({"search_area": "Hackney"})))
        self.assertIn("error", payload)
        self.assertIn("Missing filter_diagnostics", payload["error"])

    def test_ranks_single_rule_impact_and_recommendation(self) -> None:
        source = {
            "search_area": "Hackney",
            "total_results": 2,
            "filter_diagnostics": {
                "accepted_count": 2,
                "reject_reason_counts": {"price_over_budget": 3},
                "constraint_impact_if_relaxed": {
                    "price_over_budget": {
                        "label": "Relax max price",
                        "newly_eligible_if_only_this_rule_relaxed": 4,
                        "still_blocked_by_other_rules": 1,
                    },
                    "parking_not_detected": {
                        "label": "Relax parking requirement",
                        "newly_eligible_if_only_this_rule_relaxed": 1,
                        "still_blocked_by_other_rules": 5,
                    },
                },
            },
        }
        payload = json.loads(analyze_constraint_impact(json.dumps(source)))
        self.assertEqual(payload["search_area"], "Hackney")
        self.assertEqual(payload["accepted_count"], 2)
        self.assertEqual(payload["ranked_single_rule_impact"][0]["rule_key"], "price_over_budget")
        self.assertIn("Largest single blocker", payload["recommendation"])


if __name__ == "__main__":
    unittest.main()
