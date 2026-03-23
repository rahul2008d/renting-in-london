from __future__ import annotations

import ast
import pathlib
import re
import unittest
from unittest import mock

from tools import commute_time


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"


class _DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _unused_private_helpers(py_file: pathlib.Path) -> list[str]:
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    private_funcs: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            private_funcs.append(node.name)

    unused: list[str] = []
    for func_name in private_funcs:
        occurrences = len(re.findall(rf"\\b{re.escape(func_name)}\\b", source))
        if occurrences <= 1:
            unused.append(func_name)

    return unused


class TestToolsOptimizationAudit(unittest.TestCase):
    def setUp(self) -> None:
        commute_time.COMMUTE_CACHE.clear()
        commute_time.SERPAPI_DISABLED_UNTIL = 0.0

    @unittest.expectedFailure
    def test_no_unused_private_helpers(self) -> None:
        all_unused: dict[str, list[str]] = {}
        for py_file in sorted(TOOLS_DIR.glob("*.py")):
            unused = _unused_private_helpers(py_file)
            if unused:
                all_unused[py_file.name] = unused

        self.assertEqual(
            all_unused,
            {},
            f"Unused private helpers found: {all_unused}",
        )

    @unittest.expectedFailure
    def test_decision_ranker_does_not_keep_unused_score_breakdown(self) -> None:
        content = (TOOLS_DIR / "decision_ranker.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "score, score_breakdown = _soft_score(prop)",
            content,
            "Unused local variable `score_breakdown` still exists.",
        )

    def test_rightmove_search_avoids_duplicate_fetch_fallback(self) -> None:
        content = (TOOLS_DIR / "rightmove_search.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "if page_properties is None:\n                        page_properties, page_result_count = _fetch_properties_from_search_page(client, page_params)",
            content,
            "Potential duplicate page fetch path is still present in search loop.",
        )

    def test_commute_cache_prevents_duplicate_provider_calls(self) -> None:
        fake_payload = {
            "provider": "serpapi_google_maps",
            "journey_options": [{"total_duration_minutes": 31}],
        }

        with mock.patch.object(commute_time.httpx, "Client", return_value=_DummyClient()):
            with mock.patch.object(
                commute_time,
                "_try_serpapi_google_maps_commute",
                return_value=fake_payload,
            ) as serpapi_mock:
                first = commute_time.calculate_commute(51.5, -0.1, "22 Bishopsgate, London EC2N 4BQ")
                second = commute_time.calculate_commute(51.5, -0.1, "22 Bishopsgate, London EC2N 4BQ")

        self.assertEqual(first, second)
        self.assertEqual(serpapi_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
