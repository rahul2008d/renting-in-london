from __future__ import annotations

import json
import unittest

from tools.area_intel import get_area_profile


class TestAreaIntelTool(unittest.TestCase):
    def test_requires_area_name(self) -> None:
        payload = json.loads(get_area_profile("   "))
        self.assertIn("error", payload)
        self.assertEqual(payload["error"], "area_name is required.")

    def test_returns_profile_for_known_area(self) -> None:
        payload = json.loads(get_area_profile("Hackney"))
        self.assertTrue(payload["found"])
        self.assertEqual(payload["area"], "Hackney")
        self.assertEqual(payload["zone"], 2)
        self.assertIsInstance(payload.get("vibe"), str)
        self.assertIn("transport", payload)
        self.assertIn("supermarkets", payload)

    def test_returns_suggestions_for_unknown_area(self) -> None:
        payload = json.loads(get_area_profile("MadeUpAreaForTest"))
        self.assertFalse(payload["found"])
        self.assertEqual(payload["area"], "MadeUpAreaForTest")
        self.assertIn("suggested_areas", payload)
        self.assertIsInstance(payload["suggested_areas"], list)


if __name__ == "__main__":
    unittest.main()
