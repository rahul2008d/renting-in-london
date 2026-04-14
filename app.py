import re
import time

import httpx

import streamlit as st
from pydantic import BaseModel, ConfigDict, ValidationError

from data.london_areas import LONDON_AREAS


FIXED_WORKPLACE = "22 Bishopsgate, London EC2N 4BQ"
FIXED_PRIORITY = "balanced"
FIXED_COMMUTE_PREFERENCE = "fastest"
DEFAULT_STARTER_PROMPT = "List amazing homes across london"
ALL_LONDON_AREAS = sorted(LONDON_AREAS.keys())
AGENT_COMPLETION_MAX_RETRIES = 2
LISTING_QUERY_MARKERS = [
    "find",
    "search",
    "rental",
    "rent",
    "property",
    "flat",
    "apartment",
    "house",
    "listing",
    "rightmove",
    "commute",
    "london",
    "bed",
    "bath",
    "parking",
    "furnished",
]
PROPERTY_LINK_ID_PATTERN = re.compile(r"/properties/(\d+)")
REQUIRED_SECTION_HEADINGS = (
    "### Top picks now",
    "### Good with trade-offs",
    "### Rejected with reasons",
)


class ListingBlockModel(BaseModel):
    title: str
    at_a_glance: str
    confidence: str
    trade_offs_or_risks: str
    commute_lens: str
    nearest_stations: str
    key_features: str
    lettings_details: str
    epc_rating: str
    amenities_summary: str
    agent_contact: str
    summary: str
    commute_map: str
    link: str


class CompactListingModel(BaseModel):
    """Phase 2 compact card: minimum fields from search results only."""

    model_config = ConfigDict(extra="ignore")

    title: str
    summary_line: str
    link: str


def _looks_like_listing_query(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(marker in text for marker in LISTING_QUERY_MARKERS)


def _normalize_agent_reply_markdown(reply: str) -> str:
    normalized = (reply or "").strip()
    if not normalized:
        return normalized

    heading_map = {
        "Top picks now": "### Top picks now",
        "Good with trade-offs": "### Good with trade-offs",
        "Rejected with reasons": "### Rejected with reasons",
        "Supply Bottleneck Report": "### Supply Bottleneck Report",
        "Notes on areas": "### Notes on areas",
        "Next steps": "### Next steps",
    }

    for raw, heading in heading_map.items():
        pattern = re.compile(rf"(?im)^\s*{re.escape(raw)}\s*$")
        normalized = pattern.sub(heading, normalized)

    return normalized


def _format_listing_cards_markdown(reply: str) -> str:
    lines = (reply or "").splitlines()
    if not lines:
        return reply

    title_pattern = re.compile(r"^\s*(\d+\)|\d+\.)\s+(.+?)\s*$")
    out: list[str] = []
    in_listing_block = False

    for raw in lines:
        title_match = title_pattern.match(raw)
        if title_match:
            if in_listing_block:
                out.append("")
                out.append("---")
                out.append("")
            number = title_match.group(1).strip().rstrip('.)')
            title = title_match.group(2).strip()
            out.append(f"#### {number}. {title}")
            in_listing_block = True
            continue

        out.append(raw)

    return "\n".join(out)


def _format_key_value_labels(reply: str) -> str:
    lines = (reply or "").splitlines()
    if not lines:
        return reply

    kv_pattern = re.compile(r"^(\s*-\s*)([^:`][^:]{1,60}?)(:\s+)(.+)$")
    out: list[str] = []
    for raw in lines:
        match = kv_pattern.match(raw)
        if not match:
            out.append(raw)
            continue

        prefix, key, separator, value = match.groups()
        normalized_key = " ".join(key.strip().split())
        out.append(f"{prefix}`{normalized_key}`{separator}{value}")

    return "\n".join(out)


def _render_property_images(reply: str) -> str:
    """Convert image bullet lines into compact thumbnail rows."""
    lines = (reply or "").splitlines()
    out: list[str] = []
    for line in lines:
        img_match = re.match(
            r"^\s*-\s*(?:`Images?`|Images?)\s*:\s*(.+)\s*$",
            line,
        )
        if img_match:
            urls_text = img_match.group(1).strip()
            urls = [u.strip().rstrip(",") for u in re.split(r"[,\s]+", urls_text)
                    if u.strip().startswith("http")]
            if urls:
                imgs_html = "".join(
                    f'<a href="{url}" target="_blank">'
                    f'<img src="{url}" style="height:110px; width:auto; '
                    f'border-radius:6px; object-fit:cover; margin-right:4px;" '
                    f'onerror="this.style.display=\'none\'">'
                    f'</a>'
                    for url in urls[:3]
                )
                out.append(
                    f'<div style="display:flex; flex-wrap:wrap; gap:4px; '
                    f'margin:6px 0 10px 16px;">{imgs_html}</div>'
                )
        else:
            out.append(line)
    return "\n".join(out)


def _finalize_listing_reply(reply: str) -> str:
    formatted = _format_listing_cards_markdown(reply)
    formatted = _add_section_counts(formatted)
    formatted = _format_key_value_labels(formatted)
    formatted = _render_property_images(formatted)
    return formatted


def _markdown_to_basic_html(md: str) -> str:
    """Convert markdown to basic HTML for the export report."""
    lines = md.splitlines()
    html_lines: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Skip lines that are already HTML (from _render_property_images)
        if re.search(r"<(?:div|img|a)\b", stripped):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(line)
            continue

        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
            continue

        # Headings
        if stripped.startswith("### #"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
            continue
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
            continue
        if stripped.startswith("#### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h4>{stripped[5:]}</h4>")
            continue

        # Horizontal rule
        if stripped == "---":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<hr>")
            continue

        # Images
        img_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if img_match:
            alt, src = img_match.groups()
            html_lines.append(f'<img src="{src}" alt="{alt}">')
            continue

        # List items
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
            content = re.sub(
                r"\[([^\]]+)\]\(([^)]+)\)",
                r'<a href="\2">\1</a>',
                content,
            )
            content = re.sub(
                r"(https?://\S+)",
                r'<a href="\1">\1</a>',
                content,
            )
            html_lines.append(f"<li>{content}</li>")
            continue

        # Regular paragraph
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        content = re.sub(r"`([^`]+)`", r"<code>\1</code>", stripped)
        content = re.sub(
            r"(https?://\S+)",
            r'<a href="\1">\1</a>',
            content,
        )
        html_lines.append(f"<p>{content}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def _extract_shortlist_html(messages: list[dict]) -> str | None:
    """Extract property cards from assistant messages and build a standalone HTML report."""
    assistant_messages = [
        m["content"] for m in messages if m["role"] == "assistant"
    ]
    if not assistant_messages:
        return None

    full_content = "\n\n---\n\n".join(assistant_messages)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>London Rental Shortlist</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 900px; margin: 0 auto; padding: 20px;
         background: #f8f9fa; color: #1a1a2e; }}
  h1 {{ color: #16213e; border-bottom: 3px solid #0f3460; padding-bottom: 10px; }}
  h3 {{ color: #0f3460; margin-top: 30px; border-left: 4px solid #0f3460;
        padding-left: 10px; }}
  h4 {{ background: #e2e8f0; padding: 8px 12px; border-radius: 6px;
        margin-top: 20px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 4px; line-height: 1.6; }}
  a {{ color: #0f3460; }}
  code {{ background: #e2e8f0; padding: 2px 6px; border-radius: 4px;
          font-size: 0.9em; }}
  hr {{ border: none; border-top: 1px solid #cbd5e0; margin: 30px 0; }}
  .meta {{ color: #718096; font-size: 0.85em; margin-top: 40px;
           border-top: 1px solid #cbd5e0; padding-top: 10px; }}
  img {{ max-width: 100%; height: auto; border-radius: 8px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>London Rental Shortlist</h1>
<p>Generated from London Rental Agent</p>
{_markdown_to_basic_html(full_content)}
<div class="meta">
  <p>Workplace: 22 Bishopsgate, London EC2N 4BQ</p>
  <p>Filters: 2+ bed, 2+ bath, furnished, max £2300 pcm, parking preferred</p>
</div>
</body>
</html>"""
    return html


def _add_section_counts(reply: str) -> str:
    lines = (reply or "").splitlines()
    if not lines:
        return reply

    headings = {
        "### Top picks now": "### Top picks now",
        "### Good with trade-offs": "### Good with trade-offs",
        "### Rejected with reasons": "### Rejected with reasons",
    }
    heading_map: dict[int, str] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for prefix, normalized in headings.items():
            if stripped.startswith(prefix):
                heading_map[idx] = normalized

    if not heading_map:
        return reply

    positions = sorted(heading_map.keys())
    for pos_i, start in enumerate(positions):
        end = positions[pos_i + 1] if pos_i + 1 < len(positions) else len(lines)
        count = sum(1 for line in lines[start + 1 : end] if re.match(r"^\s*####\s+", line))
        lines[start] = f"{heading_map[start]} ({count})"

    return "\n".join(lines)


def _extract_property_id_from_link(link: str) -> str | None:
    if not isinstance(link, str):
        return None
    match = PROPERTY_LINK_ID_PATTERN.search(link)
    return match.group(1) if match else None


def _agent_listing_output_contract() -> str:
    return (
        "Output contract for this response:\n"
        "- Treat search scope as anywhere in London (do not ask for preferred areas).\n"
        "- Search broadly across London areas before finalizing picks.\n"
        "- Use markdown headings exactly: '### Top picks now', '### Good with trade-offs', '### Rejected with reasons'.\n"
        "- Number properties continuously across all sections (do not restart at 1 for each section).\n"
        "- For the initial search response, use this exact compact card structure per property (parse-friendly):\n"
        "  <number>) <Address, Area>\n"
        "  - Summary line: <price> | <beds> bed | <baths> bath | <type> | Zone <n> | Parking: <confirmed/unconfirmed/excluded>\n"
        "  - Amenity tags: <tag1>, <tag2>, ... (omit line if empty)\n"
        "  - Floor area: <sqft> sq ft (omit line if null)\n"
        "  - Quality signals: <signal1>, <signal2>, <signal3> (omit if none detected)\n"
        "  - Recommendation: <Highly Recommended/Worth Viewing/Consider If Flexible/Low Priority>\n"
        "  - Trade-off: <reason> (omit in Top picks; include only under Good with trade-offs)\n"
        "  - Link: https://www.rightmove.co.uk/properties/<id>\n"
        "- Full detailed cards with all fields are only required when the user requests details on a specific property.\n"
        "- For each property, use a numbered title line or `####` title as a clean readable property heading (address/area only, no Rightmove ID in title).\n"
        "- When giving full detail (on user request), for each property include bullets for: At a glance, Confidence, "
        "Trade-offs or risks, Commute lens, Nearest stations, Key features, Lettings details, EPC rating, Amenities summary, Agent contact, "
        "Summary, Commute map, Link.\n"
        "- Confidence must be one of: High, Medium, Low.\n"
        "- If sq ft can be inferred from listing/details, include it in At a glance.\n"
        "- Commute lens must respect commute preference (fastest/least walking/fewest changes).\n"
        "- Commute lens must include concrete numbers (duration in minutes and at least one of walking minutes or changes).\n"
        "- Do not include a 'Why it matches' line.\n"
        "- Commute map must be a Google Maps directions URL for origin property coordinates to 22 Bishopsgate (not a Rightmove link).\n"
        "- Summary must be substantive (at least 2 sentences with practical pros/cons).\n"
        "- Include Rightmove URL links.\n"
        "- Keep it factual, no fabricated details."
    )


def _split_listing_blocks(text: str) -> list[dict[str, str]]:
    lines = (text or "").splitlines()
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    title_pattern = re.compile(r"^\s*(?:\d+\)|\d+\.|####)\s+(.+?)\s*$")
    bullet_pattern = re.compile(r"^\s*-\s*([^:]+):\s*(.+?)\s*$")

    # Full Phase-3 cards + Phase-2 compact (one-line summary, optional tags/score lines).
    key_map = {
        "at a glance": "at_a_glance",
        "confidence": "confidence",
        "trade-offs or risks": "trade_offs_or_risks",
        "commute lens": "commute_lens",
        "nearest stations": "nearest_stations",
        "key features": "key_features",
        "lettings details": "lettings_details",
        "epc rating": "epc_rating",
        "amenities summary": "amenities_summary",
        "agent contact": "agent_contact",
        "summary": "summary",
        "commute map": "commute_map",
        "link": "link",
        "rightmove link": "link",
        "one-line summary": "summary_line",
        "summary line": "summary_line",
        "amenity tags": "amenity_tags",
        "floor area": "floor_area",
        "score": "score",
        "trade-off": "trade_off_reason",
        "trade-offs": "trade_off_reason",
        "quality signals": "quality_signals",
        "recommendation": "recommendation",
    }

    for raw in lines:
        title_match = title_pattern.match(raw)
        if title_match:
            if current:
                blocks.append(current)
            current = {"title": title_match.group(1).strip()}
            continue

        if current:
            bullet_match = bullet_pattern.match(raw)
            if not bullet_match:
                continue
            label = bullet_match.group(1).strip().lower()
            value = bullet_match.group(2).strip()
            mapped = key_map.get(label)
            if mapped:
                current[mapped] = value

    if current:
        blocks.append(current)

    return blocks


def _coerce_compact_listing_fields(block: dict[str, str]) -> dict[str, str]:
    """Build minimal fields for CompactListingModel from parsed bullets."""
    title = (block.get("title") or "").strip()
    summary_line = (
        (block.get("summary_line") or "").strip()
        or (block.get("at_a_glance") or "").strip()
    )
    link = (block.get("link") or "").strip()
    return {"title": title, "summary_line": summary_line, "link": link}


def _validate_full_listing_block(
    idx: int,
    model: ListingBlockModel,
    commute_preference: str,
) -> list[str]:
    """Phase 3: format-only checks (no live API re-fetch; data accuracy is the agent's job)."""
    issues: list[str] = []

    if model.confidence.strip().lower() not in {"high", "medium", "low"}:
        issues.append(f"listing_{idx}: invalid_confidence_value")

    property_id = _extract_property_id_from_link(model.link)
    if not property_id:
        issues.append(f"listing_{idx}: invalid_property_link")

    commute_map_lower = model.commute_map.lower()
    if "rightmove" in commute_map_lower:
        issues.append(f"listing_{idx}: commute_map_points_to_rightmove")
    if "google.com/maps" not in commute_map_lower and "maps.google" not in commute_map_lower:
        issues.append(f"listing_{idx}: commute_map_missing_google_directions_link")

    summary_word_count = len(re.findall(r"\b\w+\b", model.summary))
    if summary_word_count < 20:
        issues.append(f"listing_{idx}: summary_too_brief")

    pref_label = commute_preference.replace("_", " ").lower()
    if pref_label not in model.commute_lens.lower():
        issues.append(f"listing_{idx}: commute_preference_label_missing")

    commute_lens_lower = model.commute_lens.lower()
    if not ("min" in commute_lens_lower or "minute" in commute_lens_lower):
        issues.append(f"listing_{idx}: commute_lens_missing_duration_units")

    return issues


def _validate_listing_blocks_with_pydantic(reply: str, commute_preference: str) -> list[str]:
    """Validate listing blocks: full Phase-3 cards get strict checks; Phase-2 compact cards only need valid shape."""
    listing_issues: list[str] = []
    blocks = _split_listing_blocks(reply)
    if not blocks:
        return ["no_listing_blocks"]

    block_modes: list[str] = []

    for idx, block in enumerate(blocks, start=1):
        title = str(block.get("title") or "")
        if "rightmove id" in title.lower():
            listing_issues.append(f"listing_{idx}: title_contains_rightmove_id")

        full_model: ListingBlockModel | None = None
        try:
            full_model = ListingBlockModel.model_validate(block)
        except ValidationError:
            full_model = None

        if full_model is not None:
            block_modes.append("full")
            listing_issues.extend(_validate_full_listing_block(idx, full_model, commute_preference))
            continue

        compact_dict = _coerce_compact_listing_fields(block)
        try:
            CompactListingModel.model_validate(compact_dict)
        except ValidationError:
            block_modes.append("fail")
            listing_issues.append(f"listing_{idx}: listing_block_neither_full_nor_compact")
            continue

        block_modes.append("compact")

    # Phase 2: all compact cards — never trigger per-listing retries (commute/EPC/link checks).
    if blocks and block_modes and all(m == "compact" for m in block_modes):
        return []

    return listing_issues


def _missing_listing_sections(reply: str, commute_preference: str) -> list[str]:
    if not reply.strip():
        return ["empty_response"]

    lowered_reply = reply.lower()
    missing = [section for section in REQUIRED_SECTION_HEADINGS if section.lower() not in lowered_reply]

    no_results_pattern = (
        "no strong matches right now" in lowered_reply
        and "no maybe-matches right now" in lowered_reply
    )
    if not no_results_pattern:
        missing.extend(_validate_listing_blocks_with_pydantic(reply, commute_preference))

    if "why it matches" in lowered_reply:
        missing.append("deprecated_field_present::Why it matches")

    return missing


def _agent_retry_prompt(base_context: str, first_reply: str, issues: list[str]) -> str:
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    return (
        f"{base_context}\n\n"
        "Your previous answer is incomplete for a rental listing workflow.\n"
        "You must call tools again and regenerate a complete answer.\n"
        "Missing items:\n"
        f"{issue_text}\n\n"
        "Requirements:\n"
        "- Search anywhere in London (broad coverage).\n"
        "- Run decision ranking before recommendations.\n"
        "- For all shortlisted properties, call property details + commute + local amenities before writing.\n"
        "- Include EPC rating and include sq ft in At a glance when available.\n"
        "- Respect commute preference and mention it in Commute lens.\n"
        "- Commute lens must include duration in minutes and concrete practical detail (changes/walking/line context).\n"
        "- Commute map must be a Google Maps directions URL (not Rightmove).\n"
        "- Summary must be at least 2 practical sentences, not a one-liner.\n"
        "- Include full property fields requested in the output contract.\n"
        "- Do not include Rightmove ID in listing heading title.\n"
        "- Do not include the 'Why it matches' field.\n"
        "- Keep markdown headings and structure exactly as requested.\n\n"
        "Previous incomplete reply for reference:\n"
        f"{first_reply}"
    )

st.set_page_config(
    page_title="London Rental Agent",
    page_icon="🏠",
    layout="wide",
)

st.markdown(
        """
        <style>
            :root {
                --bg-main: #0f1720;
                --bg-panel: #141d28;
                --card-bg: #1a2430;
                --card-border: #2f4154;
                --text-main: #ecf2f9;
                --text-muted: #a9b8c8;
                --accent-cyan: #4fa0c4;
                --accent-blue: #7db2ff;
            }

            .stApp {
                color: var(--text-main);
                background:
                    radial-gradient(1050px 320px at -8% -12%, rgba(79, 160, 196, 0.14), transparent),
                    radial-gradient(900px 280px at 108% -10%, rgba(125, 178, 255, 0.12), transparent),
                    linear-gradient(180deg, #121c27 0%, var(--bg-main) 75%);
            }

            .stApp h1,
            .stApp h2,
            .stApp h3,
            .stApp h4,
            .stApp p,
            .stApp li,
            .stApp label,
            .stApp span,
            .stApp div {
                color: var(--text-main);
            }

            .stApp [data-testid="stCaptionContainer"] p {
                color: var(--text-muted);
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #141d28 0%, var(--bg-panel) 100%);
                border-right: 1px solid #2b3a4a;
            }

            [data-testid="stSidebar"] * {
                color: #e5edf6 !important;
            }

            .sidebar-section-title {
                margin: 0.7rem 0 0.35rem 0;
                padding: 0.4rem 0.6rem;
                border-left: 4px solid var(--accent-cyan);
                border-radius: 8px;
                background: linear-gradient(90deg, rgba(79, 160, 196, 0.2), rgba(79, 160, 196, 0.02));
                font-size: 0.95rem;
                font-weight: 700;
                letter-spacing: 0.02em;
                text-transform: uppercase;
                color: #ecf5ff;
            }

            [data-testid="stSidebar"] button {
                border: 1px solid #3b4f65 !important;
                background: #213247 !important;
            }

            [data-testid="stSidebar"] button:hover {
                border-color: #4d6989 !important;
                background: #2a3f57 !important;
            }

            [data-testid="stChatMessage"] {
                border: 1px solid var(--card-border);
                background: var(--card-bg);
                border-radius: 16px;
                padding: 0.5rem 0.7rem;
                box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
            }

            [data-testid="stChatMessage"] h3 {
                border-left: 4px solid var(--accent-cyan);
                padding-left: 0.65rem;
                margin-top: 0.75rem;
            }

            [data-testid="stChatMessage"] h4 {
                font-size: 1.12rem;
                font-weight: 700;
                line-height: 1.45;
                margin-top: 0.95rem;
                margin-bottom: 0.55rem;
                padding: 0.45rem 0.6rem;
                border-radius: 10px;
                border: 1px solid #3c5167;
                background: #223244;
            }

            .runtime-badge {
                text-align: right;
                font-size: 0.84rem;
                color: var(--text-muted);
                margin-top: 0.8rem;
                padding: 0.28rem 0.55rem;
                border: 1px solid #355069;
                border-radius: 999px;
                background: rgba(34, 50, 68, 0.72);
                display: inline-block;
                float: right;
            }

            [data-testid="stChatMessage"] hr {
                border: none;
                border-top: 1px solid #34485d;
                margin: 0.7rem 0 0.9rem 0;
            }

            [data-testid="stChatMessage"] p,
            [data-testid="stChatMessage"] li,
            [data-testid="stChatMessage"] a,
            [data-testid="stChatMessage"] code {
                white-space: normal;
                overflow-wrap: anywhere;
                word-break: break-word;
            }

            [data-testid="stChatMessage"] code {
                background: #2a3d52;
                color: #e7f1ff;
                border: 1px solid #4a6785;
                border-radius: 7px;
                padding: 0.08rem 0.35rem;
                font-size: 0.88em;
                font-weight: 600;
            }

            [data-testid="stChatMessage"] a {
                color: var(--accent-blue) !important;
                text-decoration-color: rgba(37, 99, 235, 0.35);
            }

            [data-testid="stChatMessage"] ul,
            [data-testid="stChatMessage"] ol {
                padding-left: 1.15rem;
            }

            [data-testid="stChatMessage"] p,
            [data-testid="stChatMessage"] li {
                line-height: 1.58;
            }

            [data-testid="stChatInput"] {
                background: #ffffff;
                border: 1px solid var(--card-border);
                border-radius: 14px;
            }

            .stButton > button[kind="secondary"] {
                border-radius: 12px;
            }

            @media (max-width: 900px) {
                [data-testid="stSidebar"] {
                    border-right: none;
                    border-bottom: 1px solid #263244;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
)

if "last_agent_runtime_sec" not in st.session_state:
    st.session_state.last_agent_runtime_sec = None

title_col, meta_col = st.columns([5, 2])
with title_col:
    st.title("🏠 London Rental Agent")
with meta_col:
    runtime_badge = st.empty()
    runtime_sec = st.session_state.get("last_agent_runtime_sec")
    runtime_text = f"Agent time: {runtime_sec:.2f}s" if isinstance(runtime_sec, (int, float)) else "Agent time: -"
    runtime_badge.markdown(f"<div class='runtime-badge'>{runtime_text}</div>", unsafe_allow_html=True)

st.caption("Your AI-powered home finder")

st.sidebar.title("🏠 Search Preferences")
st.sidebar.markdown("<div class='sidebar-section-title'>Mandatory Filters</div>", unsafe_allow_html=True)
st.sidebar.caption("Min 2 bedrooms")
st.sidebar.caption("Min 2 bathrooms")
st.sidebar.caption("Parking preferred (verify with agent if unconfirmed)")
st.sidebar.caption("Furnished only")
st.sidebar.caption("Max rent: £2300 pcm")
st.sidebar.caption("Max distance: 5 miles")
st.sidebar.caption("Excluded: House share, Retirement home, Student accommodation")
st.sidebar.markdown("<div class='sidebar-section-title'>Fixed Preferences</div>", unsafe_allow_html=True)
st.sidebar.caption(f"Office: {FIXED_WORKPLACE}")
st.sidebar.caption(f"Scoring mode: {FIXED_PRIORITY}")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "auto_ran_starter" not in st.session_state:
    st.session_state.auto_ran_starter = False

if "seen_property_ids" not in st.session_state:
    st.session_state.seen_property_ids = set()

if st.sidebar.button("Clear chat"):
    st.session_state.messages = []
    st.session_state.auto_ran_starter = False
    st.session_state.seen_property_ids = set()

if st.session_state.messages:
    shortlist_html = _extract_shortlist_html(st.session_state.messages)
    if shortlist_html:
        st.sidebar.download_button(
            label="Download shortlist",
            data=shortlist_html,
            file_name="london_rental_shortlist.html",
            mime="text/html",
            use_container_width=True,
        )

if st.session_state.get("seen_property_ids"):
    if st.sidebar.button("Check new listings", use_container_width=True):
        new_listing_prompt = (
            "Run a new search. After getting results, identify properties "
            "that are NOT in this list of already-seen property IDs: "
            f"{', '.join(sorted(st.session_state.seen_property_ids))}. "
            "Show ONLY properties with days_on_market <= 2 that have "
            "Rightmove IDs not in the above list. Present them under "
            "the heading '### New listings since last search'. "
            "If no new properties are found, say 'No new listings found "
            "since your last search.' Do not show the full search results "
            "- only the new ones."
        )
        _run_prompt(new_listing_prompt)

agent_error = None
if "agent" not in st.session_state:
    try:
        from agent import create_agent

        st.session_state.agent = create_agent()
    except Exception as exc:  # pragma: no cover - UI fallback path
        st.session_state.agent = None
        agent_error = str(exc)

if st.session_state.get("agent") is None:
    st.error("Agent setup is incomplete. Install dependencies and configure your .env file.")
    st.markdown("### Setup steps")
    st.markdown("1. Install dependencies: `uv sync`")
    st.markdown("2. Copy env file: `cp .env.example .env`")
    st.markdown("3. Set `OPENAI_API_KEY` in `.env`")
    st.markdown("4. Optional: set `SERPAPI_KEY` for Google Maps commute via SerpApi")
    st.markdown("5. Optional: set `GOOGLE_MAPS_API_KEY` for direct Google Directions fallback")
    st.markdown("6. Restart Streamlit after setup")
    if agent_error:
        st.caption(f"Import error: {agent_error}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=True)


def _run_prompt(prompt: str) -> None:
    context = (
        "[Mandatory filters: max_price=£2300/mo, min_bedrooms=2, min_bathrooms=2, "
        "parking=preferred_soft_verify, furnished=required, max_distance=5mi, "
        "excluded=house_share|retirement_home|student_accommodation]"
        f"[Fixed prefs: workplace={FIXED_WORKPLACE}, priority={FIXED_PRIORITY}]"
        f"[commute_preference={FIXED_COMMUTE_PREFERENCE}]"
        "[search_scope=anywhere_in_london]"
        f"[all_london_areas={'; '.join(ALL_LONDON_AREAS)}]"
    )
    context += f"\n{prompt}"

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        if st.session_state.get("agent") is None:
            reply = "Agent is not available yet. Please complete setup steps in the sidebar."
            st.markdown(reply, unsafe_allow_html=True)
        else:
            with st.spinner("Searching..."):
                try:
                    route_label = "Agent workflow (strict completion checks)"
                    run_started = time.perf_counter()
                    agent_prompt = context
                    if _looks_like_listing_query(prompt):
                        agent_prompt = f"{context}\n\n{_agent_listing_output_contract()}"

                    _TRANSIENT_NETWORK_ERRORS = (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError)
                    max_network_retries = 3
                    for _attempt in range(max_network_retries):
                        try:
                            response = st.session_state.agent(agent_prompt)
                            break
                        except _TRANSIENT_NETWORK_ERRORS as net_exc:
                            if _attempt < max_network_retries - 1:
                                wait = 2 ** _attempt
                                time.sleep(wait)
                            else:
                                raise RuntimeError(
                                    f"Network connection dropped after {max_network_retries} attempts. "
                                    "Please try again."
                                ) from net_exc

                    reply = _normalize_agent_reply_markdown(str(response))

                    if _looks_like_listing_query(prompt):
                        issues = _missing_listing_sections(reply, FIXED_COMMUTE_PREFERENCE)
                        retry_count = 0
                        while issues and retry_count < AGENT_COMPLETION_MAX_RETRIES:
                            retry_count += 1
                            retry_prompt = _agent_retry_prompt(context, reply, issues)
                            retry_response = st.session_state.agent(retry_prompt)
                            reply = _normalize_agent_reply_markdown(str(retry_response))
                            issues = _missing_listing_sections(reply, FIXED_COMMUTE_PREFERENCE)

                        # Final presentation pass for readability in chat.
                        reply = _finalize_listing_reply(reply)

                        property_ids = set(re.findall(
                            r"rightmove\.co\.uk/properties/(\d+)", reply
                        ))
                        if property_ids:
                            st.session_state.seen_property_ids.update(property_ids)

                    st.session_state.last_agent_runtime_sec = time.perf_counter() - run_started
                    runtime_badge.markdown(
                        f"<div class='runtime-badge'>Agent time: {st.session_state.last_agent_runtime_sec:.2f}s</div>",
                        unsafe_allow_html=True,
                    )
                except Exception as exc:  # pragma: no cover - runtime protection
                    reply = f"Sorry, I hit an error while processing your request: {exc}"
                    route_label = "Runtime error"

            st.caption(f"Route: {route_label}")
            st.markdown(reply, unsafe_allow_html=True)

    st.session_state.messages.append({"role": "assistant", "content": reply})


if not st.session_state.messages and not st.session_state.auto_ran_starter:
    st.session_state.auto_ran_starter = True
    _run_prompt(DEFAULT_STARTER_PROMPT)

quick_col1, quick_col2 = st.columns([2, 3])
with quick_col1:
    if st.button("Run starter search", use_container_width=True):
        _run_prompt(DEFAULT_STARTER_PROMPT)
with quick_col2:
    st.caption(f"Starter prompt: `{DEFAULT_STARTER_PROMPT}`")

if prompt := st.chat_input("Ask me anything about renting in London..."):
    _run_prompt(prompt)
