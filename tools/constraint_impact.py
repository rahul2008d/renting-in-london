from __future__ import annotations

import json

from strands import tool


def _sorted_impact_rows(impact: dict) -> list[dict]:
    rows: list[dict] = []
    for key, value in impact.items():
        if not isinstance(value, dict):
            continue
        rows.append(
            {
                "rule_key": key,
                "label": value.get("label"),
                "newly_eligible_if_relaxed": int(
                    value.get("newly_eligible_if_only_this_rule_relaxed") or 0
                ),
                "still_blocked_by_other_rules": int(
                    value.get("still_blocked_by_other_rules") or 0
                ),
            }
        )

    rows.sort(key=lambda row: row["newly_eligible_if_relaxed"], reverse=True)
    return rows


@tool
def analyze_constraint_impact(search_results_json: str) -> str:
    """Analyze which single mandatory rule is reducing results the most.

    Args:
        search_results_json: JSON string from search_london_rentals (London-wide search output).

    Returns:
        JSON string containing ranked impact insights for one-at-a-time
        rule relaxation simulation. This is analysis-only and does not modify
        enforced filters.
    """
    if not search_results_json or not search_results_json.strip():
        return json.dumps({"error": "search_results_json is required."})

    try:
        payload = json.loads(search_results_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "search_results_json is not valid JSON."})

    diagnostics = payload.get("filter_diagnostics") if isinstance(payload, dict) else None
    if not isinstance(diagnostics, dict):
        return json.dumps(
            {
                "error": "Missing filter_diagnostics in search_results_json.",
            }
        )

    impact = diagnostics.get("constraint_impact_if_relaxed")
    if not isinstance(impact, dict):
        return json.dumps(
            {
                "error": "Missing constraint impact data in filter diagnostics.",
            }
        )

    rows = _sorted_impact_rows(impact)
    top = rows[0] if rows else None

    recommendation = None
    if top and top.get("newly_eligible_if_relaxed", 0) > 0:
        recommendation = (
            f"Largest single blocker appears to be '{top.get('label')}', "
            f"which could add about {top.get('newly_eligible_if_relaxed')} properties "
            "if that one rule were relaxed while all others stayed fixed."
        )
    else:
        recommendation = (
            "No single rule relaxation appears sufficient; most rejects fail multiple rules simultaneously."
        )

    return json.dumps(
        {
            "search_area": payload.get("search_area") if isinstance(payload, dict) else None,
            "returned_count": payload.get("total_results") if isinstance(payload, dict) else None,
            "accepted_count": diagnostics.get("accepted_count"),
            "reject_reason_counts": diagnostics.get("reject_reason_counts"),
            "ranked_single_rule_impact": rows,
            "recommendation": recommendation,
        }
    )
