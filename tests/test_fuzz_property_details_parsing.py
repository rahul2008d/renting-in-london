from __future__ import annotations

import json
import random
import string
import unittest

from tools import property_details


class TestFuzzPropertyDetailsParsing(unittest.TestCase):
    def test_extract_json_blob_handles_noise(self) -> None:
        payload = {"propertyData": {"bedrooms": 2, "bathrooms": 2}}
        html = f"prefix<script>window.PAGE_MODEL = {json.dumps(payload)};</script>suffix"
        blob = property_details._extract_json_blob_from_page_model(html)
        self.assertIsNotNone(blob)
        self.assertEqual(json.loads(blob), payload)

    def test_extract_json_blob_returns_none_when_missing(self) -> None:
        self.assertIsNone(property_details._extract_json_blob_from_page_model("<html>No marker</html>"))

    def test_extract_helpers_survive_malformed_data(self) -> None:
        rng = random.Random(123)
        for _ in range(300):
            stations = []
            for _ in range(rng.randint(0, 4)):
                if rng.random() < 0.5:
                    stations.append({"name": "S", "distance": rng.random() * 5})
                else:
                    stations.append(rng.choice([None, 1, "bad", {"x": 1}]))
            prop = {
                "nearestStations": stations,
                "images": rng.choice([[], [{"id": 1}], "bad", None]),
                "propertyImages": rng.choice([
                    {"images": [{"id": 2}]},
                    {"images": []},
                    {},
                    None,
                ]),
            }

            nearest = property_details._extract_nearest_stations(prop)
            image_count = property_details._extract_image_count(prop)

            self.assertIsInstance(nearest, list)
            self.assertIsInstance(image_count, int)
            self.assertGreaterEqual(image_count, 0)

    def test_json_blob_does_not_false_positive_on_random_text(self) -> None:
        rng = random.Random(99)
        alphabet = string.ascii_letters + string.digits + "{}[]\\\";:<>=_/-"
        for _ in range(100):
            sample = "".join(rng.choice(alphabet) for _ in range(500))
            # This should never raise, and usually no marker means None.
            blob = property_details._extract_json_blob_from_page_model(sample)
            if blob is not None:
                # If it finds a blob, it should be valid JSON object text.
                parsed = json.loads(blob)
                self.assertIsInstance(parsed, dict)


if __name__ == "__main__":
    unittest.main()
