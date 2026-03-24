"""Pure helpers for extracting listing text signals (no strands @tool). Used by price_scorer."""

from __future__ import annotations

import re

# --- Individual extractors: return (value_label, score 0-100) ---


def _combined_text(text_blob: str, key_features: list[str]) -> str:
    parts = [text_blob]
    for f in key_features:
        if isinstance(f, str) and f.strip():
            parts.append(f.lower())
    return " ".join(parts)


def extract_heating_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "heat pump" in t or "underfloor heating" in t:
        return ("heat pump/underfloor", 90.0)
    if "gas central heating" in t or "gas ch" in t:
        return ("gas central", 70.0)
    if "communal heating" in t or "district heating" in t:
        return ("communal", 60.0)
    if "electric heating" in t or "storage heaters" in t or "electric radiators" in t:
        return ("electric/storage", 30.0)
    return ("unknown", 50.0)


def extract_floor_level_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "penthouse" in t or "top floor" in t:
        return ("top floor", 95.0)
    if re.search(r"\b(?:fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)\s+floor\b", t):
        return ("upper floor", 85.0)
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)\s+floor\b", t)
    if m:
        try:
            n = int(m.group(1))
            if n >= 4:
                return ("upper floor", 85.0)
            if n in (2, 3):
                return ("mid floor", 80.0)
            if n == 1:
                return ("first floor", 65.0)
        except ValueError:
            pass
    if "second floor" in t or "third floor" in t:
        return ("mid floor", 80.0)
    if "first floor" in t:
        return ("first floor", 65.0)
    if "ground floor" in t:
        return ("ground floor", 50.0)
    if "basement" in t or "lower ground" in t:
        return ("basement", 30.0)
    return ("unknown", 60.0)


def extract_facing_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "south facing" in t or "south-facing" in t:
        return ("south facing", 95.0)
    if "dual aspect" in t:
        return ("dual aspect", 90.0)
    if "west facing" in t or "west-facing" in t:
        return ("west facing", 75.0)
    if "east facing" in t or "east-facing" in t:
        return ("east facing", 70.0)
    if "north facing" in t or "north-facing" in t:
        return ("north facing", 45.0)
    return ("unknown", 60.0)


def extract_building_age_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "new build" in t or "newly built" in t:
        return ("new build", 85.0)
    if "georgian" in t:
        return ("georgian", 82.0)
    if "victorian" in t:
        return ("victorian", 80.0)
    if "edwardian" in t:
        return ("edwardian", 78.0)
    if "art deco" in t or "1930s" in t:
        return ("art deco/1930s", 72.0)
    if "warehouse conversion" in t or "converted warehouse" in t:
        return ("warehouse conversion", 75.0)
    if re.search(r"(?<!un)converted", t):
        return ("conversion", 65.0)
    if "purpose built" in t or "purpose-built" in t:
        return ("purpose built", 60.0)
    if "1960s" in t or "1970s" in t or "1980s" in t:
        return ("post-war", 40.0)
    return ("unknown", 55.0)


def extract_glazing_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "triple glazed" in t or "triple glazing" in t:
        return ("triple glazed", 90.0)
    if "double glazed" in t or "double glazing" in t or "double-glazed" in t:
        return ("double glazed", 80.0)
    if "secondary glazing" in t:
        return ("secondary glazing", 60.0)
    if "single glazed" in t or "single glazing" in t:
        return ("single glazed", 30.0)
    return ("unknown", 55.0)


def extract_noise_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if any(
        x in t
        for x in (
            "quiet street",
            "quiet road",
            "quiet cul-de-sac",
            "peaceful",
            "tranquil",
            "secluded",
        )
    ):
        return ("quiet/peaceful", 90.0)
    if "residential street" in t or "residential road" in t:
        return ("residential", 75.0)
    if "cul-de-sac" in t or "cul de sac" in t:
        return ("cul-de-sac", 85.0)
    if "main road" in t or "busy road" in t or "high street" in t or "a road" in t:
        return ("busy road", 35.0)
    if "above shop" in t or "above commercial" in t or "above restaurant" in t:
        return ("above commercial", 25.0)
    if "flight path" in t or "heathrow" in t or "city airport" in t:
        return ("flight path", 20.0)
    if "railway line" in t or "train line" in t or "near railway" in t:
        return ("near railway", 30.0)
    return ("unknown", 60.0)


def extract_outdoor_space_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "no garden" in t or "no outdoor" in t:
        return ("none", 20.0)
    if "private garden" in t or "rear garden" in t or "front and rear garden" in t:
        return ("private garden", 95.0)
    if "roof terrace" in t:
        return ("roof terrace", 90.0)
    if "balcony" in t or "terrace" in t or "juliet balcony" in t:
        return ("balcony/terrace", 75.0)
    if "patio" in t:
        return ("patio", 70.0)
    if "communal garden" in t or "shared garden" in t:
        return ("communal garden", 50.0)
    return ("unknown", 40.0)


def extract_security_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if "concierge" in t or "24 hour concierge" in t or "24-hour concierge" in t:
        return ("concierge", 95.0)
    if "porter" in t or "porterage" in t:
        return ("porter", 90.0)
    if "gated" in t or "gated development" in t or "gated community" in t:
        return ("gated", 80.0)
    if "video entry" in t or "video entryphone" in t or "entry phone" in t:
        return ("video entry", 70.0)
    if "secure entry" in t or "secure entrance" in t or "fob entry" in t:
        return ("secure entry", 65.0)
    if "cctv" in t:
        return ("cctv", 60.0)
    return ("unknown", 45.0)


def extract_storage_signal(text_blob: str, key_features: list[str]) -> tuple[str, float]:
    t = _combined_text(text_blob, key_features)
    if (
        "walk-in wardrobe" in t
        or "walk in wardrobe" in t
        or "dressing room" in t
    ):
        return ("walk-in wardrobe", 90.0)
    n_fitted = len(re.findall(r"fitted wardrobe", t))
    if n_fitted >= 2 or "wardrobes throughout" in t:
        return ("multiple fitted", 80.0)
    if "fitted wardrobe" in t or "built-in wardrobe" in t or "built in wardrobe" in t:
        return ("fitted wardrobe", 70.0)
    if "storage cupboard" in t or "storage room" in t or "utility room" in t:
        return ("storage room", 65.0)
    if "loft" in t or "loft space" in t:
        return ("loft", 55.0)
    if "cellar" in t:
        return ("cellar", 55.0)
    return ("unknown", 35.0)


def extract_hidden_costs(text_blob: str, key_features: list[str]) -> dict:
    t = _combined_text(text_blob, key_features)
    service_charge: str | None = None
    ground_rent: str | None = None
    council_tax_band: str | None = None
    bills_included: bool | None = None

    sc_m = re.search(
        r"service\s+charge[:\s]*£?\s*([\d,.]+)\s*(?:pcm|per month|/month|/m)?",
        t,
        re.IGNORECASE,
    )
    if sc_m:
        service_charge = sc_m.group(1).strip()

    gr_m = re.search(
        r"ground\s+rent[:\s]*£?\s*([\d,.]+)",
        t,
        re.IGNORECASE,
    )
    if gr_m:
        ground_rent = gr_m.group(1).strip()

    ct_m = re.search(
        r"council\s+tax\s*(?:band)?[:\s]*([a-h])\b",
        t,
        re.IGNORECASE,
    )
    if ct_m:
        council_tax_band = ct_m.group(1).upper()

    if re.search(r"\bbills\s+included\b", t) or re.search(r"\bbills\s+inc\b", t):
        bills_included = True
    elif re.search(r"\bbills\s+not\s+included\b", t) or re.search(r"\bexcluding\s+bills\b", t):
        bills_included = False

    transparency_score = 40.0
    if bills_included is True:
        transparency_score = 90.0
    elif service_charge is not None:
        transparency_score = 70.0
    if council_tax_band is not None:
        transparency_score = min(100.0, transparency_score + 10.0)

    return {
        "service_charge": service_charge,
        "ground_rent": ground_rent,
        "council_tax_band": council_tax_band,
        "bills_included": bills_included,
        "transparency_score": transparency_score,
    }


def compute_epc_score(epc_rating: str | None) -> float:
    if not epc_rating or not str(epc_rating).strip():
        return 50.0
    letter = str(epc_rating).strip().upper()[:1]
    return {
        "A": 100.0,
        "B": 85.0,
        "C": 70.0,
        "D": 55.0,
        "E": 40.0,
        "F": 20.0,
        "G": 10.0,
    }.get(letter, 50.0)


def compute_listing_quality_score(signals: dict[str, float], epc_score: float, hidden_transparency: float) -> float:
    """Weighted average of component scores (0-100 each)."""
    heating = signals["heating"]
    floor_s = signals["floor_level"]
    facing_s = signals["facing"]
    building_age_s = signals["building_age"]
    glazing_s = signals["glazing"]
    noise_s = signals["noise"]
    outdoor_s = signals["outdoor_space"]
    security_s = signals["security"]
    storage_s = signals["storage"]

    natural_light = (floor_s + facing_s) / 2.0
    building_quality = (building_age_s + glazing_s) / 2.0

    total = (
        heating * 0.12
        + natural_light * 0.12
        + building_quality * 0.12
        + noise_s * 0.15
        + outdoor_s * 0.12
        + security_s * 0.08
        + storage_s * 0.07
        + epc_score * 0.12
        + hidden_transparency * 0.10
    )
    return max(0.0, min(100.0, total))


def _build_top_signals(signal_entries: list[tuple[str, float]]) -> list[str]:
    """Up to 3 with score >= 75; if fewer than 3, add highest above 60."""
    sorted_hi = sorted(
        [(v, s) for v, s in signal_entries if s >= 75.0],
        key=lambda x: -x[1],
    )
    out = [v for v, _ in sorted_hi[:3]]
    if len(out) >= 3:
        return out
    rest = sorted(
        [(v, s) for v, s in signal_entries if s > 60.0 and v not in out],
        key=lambda x: -x[1],
    )
    for v, _ in rest:
        if len(out) >= 3:
            break
        out.append(v)
    return out[:3]


def extract_all_signals(
    text_blob: str,
    key_features: list[str],
    epc_rating: str | None,
) -> dict:
    h_val, h_sc = extract_heating_signal(text_blob, key_features)
    fl_val, fl_sc = extract_floor_level_signal(text_blob, key_features)
    fa_val, fa_sc = extract_facing_signal(text_blob, key_features)
    ba_val, ba_sc = extract_building_age_signal(text_blob, key_features)
    gl_val, gl_sc = extract_glazing_signal(text_blob, key_features)
    n_val, n_sc = extract_noise_signal(text_blob, key_features)
    o_val, o_sc = extract_outdoor_space_signal(text_blob, key_features)
    sec_val, sec_sc = extract_security_signal(text_blob, key_features)
    st_val, st_sc = extract_storage_signal(text_blob, key_features)
    hidden = extract_hidden_costs(text_blob, key_features)
    epc_sc = compute_epc_score(epc_rating)

    score_map = {
        "heating": h_sc,
        "floor_level": fl_sc,
        "facing": fa_sc,
        "building_age": ba_sc,
        "glazing": gl_sc,
        "noise": n_sc,
        "outdoor_space": o_sc,
        "security": sec_sc,
        "storage": st_sc,
    }

    listing_quality = compute_listing_quality_score(score_map, epc_sc, float(hidden["transparency_score"]))

    signal_entries = [
        (h_val, h_sc),
        (fl_val, fl_sc),
        (fa_val, fa_sc),
        (ba_val, ba_sc),
        (gl_val, gl_sc),
        (n_val, n_sc),
        (o_val, o_sc),
        (sec_val, sec_sc),
        (st_val, st_sc),
    ]
    top_signals = _build_top_signals(signal_entries)

    return {
        "signals": {
            "heating": {"value": h_val, "score": h_sc},
            "floor_level": {"value": fl_val, "score": fl_sc},
            "facing": {"value": fa_val, "score": fa_sc},
            "building_age": {"value": ba_val, "score": ba_sc},
            "glazing": {"value": gl_val, "score": gl_sc},
            "noise": {"value": n_val, "score": n_sc},
            "outdoor_space": {"value": o_val, "score": o_sc},
            "security": {"value": sec_val, "score": sec_sc},
            "storage": {"value": st_val, "score": st_sc},
        },
        "epc_score": epc_sc,
        "hidden_costs": hidden,
        "listing_quality_score": round(listing_quality, 2),
        "top_signals": top_signals,
    }


def recommendation_tier(total_score: float) -> str:
    if total_score >= 75.0:
        return "Highly Recommended"
    if total_score >= 60.0:
        return "Worth Viewing"
    if total_score >= 45.0:
        return "Consider If Flexible"
    return "Low Priority"
