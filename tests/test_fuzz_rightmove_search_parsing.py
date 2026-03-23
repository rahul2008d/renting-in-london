from __future__ import annotations

import json
import random
import unittest

from tools import rightmove_search


def _random_prop(rng: random.Random) -> dict:
    maybe_text = rng.choice([
        "furnished with parking in London E2",
        "unfurnished student accommodation",
        "retirement flat",
        "garage and driveway",
        "",
        None,
    ])
    return {
        "id": rng.randint(1, 999999),
        "price": {"amount": rng.choice([0, 1200, 2000, 2600, None, "bad"])},
        "bedrooms": rng.choice([0, 1, 2, 3, None, "2"]),
        "bathrooms": rng.choice([0, 1, 2, 3, None, "2"]),
        "distance": rng.choice([None, 1.2, 4.9, 6.5, "bad"]),
        "students": rng.choice([True, False, None]),
        "displayAddress": rng.choice([
            "Hackney, London E8",
            "Manchester M1",
            "",
            None,
        ]),
        "summary": maybe_text,
        "propertySubType": rng.choice(["Flat", "House", "Studio", None]),
        "propertyTypeFullDescription": maybe_text,
        "displayStatus": maybe_text,
        "keyFeatures": rng.choice([
            ["Furnished", "Parking"],
            [{"description": "Allocated parking"}],
            [],
            None,
        ]),
        "keywords": rng.choice([["parking"], ["furnished"], [], None]),
        "location": rng.choice([
            {"latitude": 51.5, "longitude": -0.1},
            {"latitude": 53.0, "longitude": -2.0},
            {},
            None,
        ]),
    }


class TestFuzzRightmoveSearchParsing(unittest.TestCase):
    def test_extract_next_data_json_parses_valid_script(self) -> None:
        next_data = {"props": {"pageProps": {"searchResults": {"properties": [], "resultCount": 0}}}}
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data)
            + "</script>"
        )
        parsed = rightmove_search._extract_next_data_json(html)
        self.assertEqual(parsed, next_data)

    def test_extract_typeahead_items_handles_various_shapes(self) -> None:
        samples = [
            [{"locationIdentifier": "REGION^1"}],
            {"typeAheadLocations": [{"locationIdentifier": "OUTCODE^1"}]},
            {"items": [{"locationIdentifier": "REGION^2"}]},
            {"suggestions": []},
            None,
            "bad",
            {"unknown": 1},
        ]
        for sample in samples:
            items = rightmove_search._extract_typeahead_items(sample)
            self.assertIsInstance(items, list)

    def test_reject_reason_extraction_never_crashes_on_malformed_props(self) -> None:
        rng = random.Random(2026)
        for _ in range(400):
            prop = _random_prop(rng)
            reasons = rightmove_search._mandatory_reject_reasons(prop)
            self.assertIsInstance(reasons, list)

    def test_constraint_impact_summary_shape_is_stable(self) -> None:
        rejected = [
            ["price_over_budget", "parking_not_detected"],
            ["price_over_budget"],
            ["furnished_not_detected", "distance_over_limit"],
        ]
        summary = rightmove_search._build_constraint_impact_summary(rejected)
        self.assertIsInstance(summary, dict)
        self.assertIn("price_over_budget", summary)
        self.assertIn("newly_eligible_if_only_this_rule_relaxed", summary["price_over_budget"])


if __name__ == "__main__":
    unittest.main()
