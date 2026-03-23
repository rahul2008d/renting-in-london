from __future__ import annotations

import random
import unittest

from tools import commute_time


def _random_scalar(rng: random.Random):
    choices = [
        None,
        "",
        "text",
        rng.randint(-1000, 1000),
        rng.random() * 100,
        True,
        False,
    ]
    return rng.choice(choices)


def _random_json_like(rng: random.Random, depth: int = 0):
    if depth > 2:
        return _random_scalar(rng)
    kind = rng.choice(["dict", "list", "scalar"])
    if kind == "scalar":
        return _random_scalar(rng)
    if kind == "list":
        return [_random_json_like(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    out = {}
    for _ in range(rng.randint(0, 5)):
        out[f"k{rng.randint(0, 9)}"] = _random_json_like(rng, depth + 1)
    return out


class TestFuzzCommuteTimeParsing(unittest.TestCase):
    def test_format_google_route_never_crashes_on_malformed_payloads(self) -> None:
        rng = random.Random(42)
        for _ in range(300):
            route = _random_json_like(rng)
            if not isinstance(route, dict):
                route = {"legs": route}
            result = commute_time._format_google_route(route)
            self.assertIsInstance(result, dict)
            self.assertIn("total_duration_minutes", result)
            self.assertIn("legs", result)

    def test_format_serpapi_direction_never_crashes_on_malformed_payloads(self) -> None:
        rng = random.Random(7)
        for _ in range(300):
            direction = _random_json_like(rng)
            if not isinstance(direction, dict):
                direction = {"trips": direction}
            result = commute_time._format_serpapi_direction(direction)
            self.assertIsInstance(result, dict)
            self.assertIn("modes_used", result)
            self.assertIn("legs", result)

    def test_coordinate_parser_rejects_garbage_and_accepts_valid(self) -> None:
        bad_values = ["", "abc", "51.5|0.1", "51.5,", ",-0.1", "1,2,3"]
        for value in bad_values:
            self.assertIsNone(commute_time._parse_coordinates(value))

        parsed = commute_time._parse_coordinates("51.5007, -0.1246")
        self.assertEqual(parsed, (51.5007, -0.1246))


if __name__ == "__main__":
    unittest.main()
