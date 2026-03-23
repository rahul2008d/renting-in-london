from __future__ import annotations

import re
from difflib import SequenceMatcher

# Regex to extract London postcode outward (e.g. E8, SW4, WC1) from address
_POSTCODE_OUTWARD = re.compile(
    r"\b(EC[1-4]|WC[12]|E[1-9]|E1[0-9]|E20|N[1-9]|N1[0-9]|N2[0-2]|"
    r"NW[1-9]|NW1[01]|SE[1-9]|SE1[0-9]|SE2[0-8]|SW[1-9]|SW1[0-9]|SW20|"
    r"W[1-9]|W1[0-4]|BR[1-8]|CR[0-9]|CR1[0-9]|DA[1-9]|DA1[0-8]|"
    r"EN[1-9]|EN1[0-1]|IG[1-9]|IG1[0-1]|KT[1-9]|KT1[0-9]|KT2[0-4]|"
    r"RM[1-9]|RM1[0-9]|SM[1-9]|SM1[0-7]|TW[1-9]|TW1[0-9]|TW2[0-0]|"
    r"UB[1-9]|UB1[0-1]|HA[0-9]|HA1[0-9])\b",
    re.IGNORECASE,
)

# Simpler fallback: match area+digit (e.g. E8, SW4, N1)
_POSTCODE_SIMPLE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b", re.IGNORECASE)

# Curated London postcode outward → TfL zone (1–6). Based on typical station coverage.
# Boroughs span zones; this gives a reasonable heuristic when area name is not in address.
POSTCODE_OUTWARD_TO_ZONE: dict[str, int] = {
    # Zone 1 – Central London
    "EC1": 1, "EC2": 1, "EC3": 1, "EC4": 1,
    "WC1": 1, "WC2": 1,
    "E1": 1, "N1": 1, "SE1": 1, "SW1": 1, "W1": 1, "NW1": 1,
    # Zone 2 – Inner ring
    "E2": 2, "E3": 2, "E8": 2, "E9": 2, "E14": 2,
    "N4": 2, "N5": 2, "N6": 2, "N7": 2, "N8": 2, "N16": 2, "N19": 2,
    "NW2": 2, "NW3": 2, "NW5": 2, "NW6": 2, "NW8": 2,
    "SE4": 2, "SE5": 2, "SE6": 2, "SE8": 2, "SE10": 2, "SE11": 2, "SE13": 2,
    "SE14": 2, "SE15": 2, "SE16": 2, "SE17": 2, "SE21": 2, "SE22": 2, "SE23": 2, "SE24": 2,
    "SW2": 2, "SW4": 2, "SW5": 2, "SW6": 2, "SW8": 2, "SW9": 2, "SW10": 2, "SW11": 2, "SW12": 2,
    "W2": 2, "W4": 2, "W6": 2, "W8": 2, "W9": 2, "W10": 2, "W11": 2, "W12": 2, "W14": 2,
    # Zone 3
    "E4": 3, "E5": 3, "E6": 3, "E7": 3, "E10": 3, "E11": 3, "E15": 3, "E16": 3, "E17": 3,
    "N9": 3, "N10": 3, "N11": 3, "N15": 3, "N17": 3, "N22": 3,
    "NW4": 3, "NW7": 3, "NW9": 3, "NW10": 3, "NW11": 3,
    "SE18": 3, "SE19": 3, "SE20": 3, "SE26": 3, "SE27": 3, "SE28": 3,
    "SW15": 3, "SW16": 3, "SW17": 3, "SW18": 3, "SW19": 3,
    "W3": 3, "W5": 3, "W7": 3, "W13": 3,
    # Zone 4
    "E18": 4, "E20": 4,
    "N12": 4, "N13": 4, "N14": 4, "N18": 4, "N20": 4, "N21": 4,
    "SE2": 4, "SE7": 4, "SE9": 4, "SE12": 4,
    "SW20": 4,
    "BR1": 4, "BR2": 4, "BR3": 4, "BR4": 4, "BR5": 4,
    "CR0": 4, "CR2": 4, "CR4": 4, "CR7": 4, "CR8": 4, "CR9": 4,
    "DA1": 4, "DA5": 4, "DA6": 4, "DA7": 4, "DA8": 4,
    "IG1": 4, "IG2": 4, "IG3": 4, "IG4": 4, "IG5": 4, "IG6": 4, "IG7": 4, "IG8": 4,
    "RM1": 4, "RM2": 4, "RM3": 4, "RM5": 4, "RM6": 4, "RM7": 4, "RM8": 4,
    "KT1": 4, "KT2": 4, "KT3": 4, "KT4": 4,
    "TW1": 4, "TW2": 4, "TW3": 4, "TW4": 4, "TW5": 4, "TW7": 4, "TW8": 4, "TW9": 4,
    "UB1": 4, "UB2": 4, "UB3": 4, "UB4": 4, "UB5": 4,
    "HA0": 4, "HA1": 4, "HA2": 4, "HA3": 4, "HA4": 4, "HA5": 4,
    "EN1": 4, "EN2": 4, "EN3": 4, "EN4": 4, "EN5": 4, "EN8": 4, "EN9": 4,
    "SM1": 4, "SM2": 4, "SM3": 4, "SM4": 4, "SM5": 4, "SM6": 4, "SM7": 4,
    # Zone 5
    "BR6": 5, "BR7": 5, "BR8": 5,
    "CR5": 5, "CR6": 5,
    "DA9": 5, "DA10": 5, "DA11": 5, "DA12": 5, "DA13": 5, "DA14": 5, "DA15": 5, "DA16": 5, "DA17": 5, "DA18": 5,
    "IG9": 5, "IG10": 5, "IG11": 5,
    "RM9": 5, "RM10": 5, "RM11": 5, "RM12": 5, "RM13": 5, "RM14": 5,
    "KT5": 5, "KT6": 5, "KT7": 5, "KT8": 5, "KT9": 5, "KT10": 5, "KT19": 5, "KT20": 5, "KT21": 5, "KT22": 5, "KT23": 5, "KT24": 5,
    "TW10": 5, "TW11": 5, "TW12": 5, "TW13": 5, "TW14": 5,
    "UB6": 5, "UB7": 5, "UB8": 5, "UB9": 5, "UB10": 5, "UB11": 5,
    "HA6": 5, "HA7": 5, "HA8": 5, "HA9": 5,
    "EN10": 5, "EN11": 5,
    "SM8": 5, "SM9": 5, "SM10": 5, "SM11": 5, "SM12": 5, "SM13": 5, "SM14": 5, "SM15": 5, "SM16": 5, "SM17": 5,
    # Zone 6
    "KT17": 6, "KT18": 6,
    "TW15": 6, "TW16": 6, "TW17": 6, "TW18": 6, "TW19": 6, "TW20": 6,
}

LONDON_AREAS = {
    "London": "REGION^87490",  # London-wide; use for search (borough IDs often fail)
    "Central London": "REGION^87490",
    "City of London": "REGION^61295",
    "Westminster": "REGION^61475",
    "Camden": "REGION^61225",
    "Islington": "REGION^61408",
    "Hackney": "REGION^61342",
    "Tower Hamlets": "REGION^61459",
    "Southwark": "REGION^61456",
    "Lambeth": "REGION^61413",
    "Kensington and Chelsea": "REGION^61389",
    "Hammersmith and Fulham": "REGION^61360",
    "Wandsworth": "REGION^61469",
    "Lewisham": "REGION^61417",
    "Greenwich": "REGION^61351",
    "Newham": "REGION^61431",
    "Waltham Forest": "REGION^61472",
    "Enfield": "REGION^61334",
    "Haringey": "REGION^61363",
    "Barnet": "REGION^61217",
    "Brent": "REGION^61258",
    "Ealing": "REGION^61322",
    "Hounslow": "REGION^61381",
    "Richmond upon Thames": "REGION^61444",
    "Kingston upon Thames": "REGION^61393",
    "Merton": "REGION^61424",
    "Sutton": "REGION^61457",
    "Croydon": "REGION^61312",
    "Bromley": "REGION^61268",
    "Bexley": "REGION^61247",
    "Havering": "REGION^61366",
    "Redbridge": "REGION^61439",
    "Barking and Dagenham": "REGION^61207",
    "Harrow": "REGION^61364",
    "Brixton": "OUTCODE^1890",
    "Clapham": "OUTCODE^1877",
    "Canary Wharf": "OUTCODE^1079",
    "Shoreditch": "OUTCODE^1083",
    "Soho": "OUTCODE^1093",
    "Covent Garden": "OUTCODE^1104",
    "Bloomsbury": "OUTCODE^1126",
    "Marylebone": "OUTCODE^1131",
    "Mayfair": "OUTCODE^1133",
    "Fitzrovia": "OUTCODE^1139",
    "Kings Cross": "OUTCODE^1148",
    "Angel": "OUTCODE^1156",
    "Dalston": "OUTCODE^1162",
    "Stoke Newington": "OUTCODE^1169",
    "Bethnal Green": "OUTCODE^1173",
    "Bow": "REGION^87495",
    "Whitechapel": "OUTCODE^1181",
    "Wapping": "OUTCODE^1184",
    "Aldgate": "OUTCODE^1188",
    "London Bridge": "OUTCODE^1191",
    "Bermondsey": "OUTCODE^1196",
    "Peckham": "OUTCODE^1205",
    "Dulwich": "OUTCODE^1211",
    "Herne Hill": "OUTCODE^1217",
    "Battersea": "OUTCODE^1220",
    "Balham": "OUTCODE^1228",
    "Tooting": "OUTCODE^1235",
    "Wimbledon": "OUTCODE^1242",
    "Putney": "OUTCODE^1249",
    "Fulham": "OUTCODE^1252",
    "Chelsea": "OUTCODE^1256",
    "Notting Hill": "OUTCODE^1261",
    "Kensington": "OUTCODE^1265",
    "Paddington": "OUTCODE^1272",
    "Maida Vale": "OUTCODE^1276",
    "Kilburn": "OUTCODE^1281",
    "Hampstead": "OUTCODE^1289",
    "Belsize Park": "OUTCODE^1294",
    "Primrose Hill": "OUTCODE^1299",
    "Highbury": "OUTCODE^1303",
    "Finsbury Park": "OUTCODE^1307",
    "Hammersmith": "REGION^85329",
    "Muswell Hill": "OUTCODE^1312",
    "Crouch End": "OUTCODE^1316",
    "Stratford": "OUTCODE^1324",
    "Leyton": "OUTCODE^1330",
    "Walthamstow": "OUTCODE^1336",
    "Mile End": "REGION^85206",
    "Blackheath": "OUTCODE^1343",
    "Deptford": "OUTCODE^1351",
    "Forest Hill": "REGION^85335",
    "Canada Water": "OUTCODE^1357",
    "Rotherhithe": "OUTCODE^1360",
    "Elephant and Castle": "OUTCODE^1366",
    "Shepherd's Bush": "REGION^85398",
    "Vauxhall": "OUTCODE^1371",
    "Nine Elms": "OUTCODE^1375",
    "Acton": "OUTCODE^1381",
    "Chiswick": "OUTCODE^1387",
    "Ealing Broadway": "OUTCODE^1391",
    "Wembley": "OUTCODE^1398",
    "Edgware": "OUTCODE^1402",
    "Romford": "OUTCODE^1409",
    "Ilford": "OUTCODE^1415",
    "Woolwich": "REGION^70391",
}


ZONE_MAP = {
    1: [
        "Central London",
        "City of London",
        "Westminster",
        "Soho",
        "Covent Garden",
        "Mayfair",
        "Marylebone",
        "Fitzrovia",
        "Aldgate",
        "London Bridge",
        "Vauxhall",
    ],
    2: [
        "Camden",
        "Islington",
        "Hackney",
        "Tower Hamlets",
        "Southwark",
        "Lambeth",
        "Clapham",
        "Brixton",
        "Canary Wharf",
        "Shoreditch",
        "Kensington",
        "Chelsea",
        "Fulham",
        "Battersea",
        "Hammersmith and Fulham",
        "Wandsworth",
        "Hampstead",
        "Highbury",
        "Bermondsey",
        "Canada Water",
        "Bow",
        "Mile End",
        "Hammersmith",
        "Shepherd's Bush",
    ],
    3: [
        "Lewisham",
        "Greenwich",
        "Newham",
        "Waltham Forest",
        "Haringey",
        "Brent",
        "Ealing",
        "Hounslow",
        "Wimbledon",
        "Putney",
        "Tooting",
        "Balham",
        "Stratford",
        "Walthamstow",
        "Acton",
        "Chiswick",
        "Wembley",
        "Forest Hill",
    ],
    4: [
        "Barnet",
        "Enfield",
        "Harrow",
        "Redbridge",
        "Barking and Dagenham",
        "Bexley",
        "Bromley",
        "Croydon",
        "Sutton",
        "Merton",
        "Kingston upon Thames",
        "Richmond upon Thames",
        "Ilford",
        "Romford",
        "Edgware",
        "Ealing Broadway",
        "Woolwich",
    ],
    5: [
        "Havering",
        "Muswell Hill",
        "Crouch End",
        "Blackheath",
    ],
    6: [
        "Hillingdon",
    ],
}


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())


def get_zone(area_name: str) -> int:
    if not area_name:
        return 3

    query = _normalize(area_name)
    for zone, names in ZONE_MAP.items():
        for name in names:
            normalized_name = _normalize(name)
            if query == normalized_name or query in normalized_name or normalized_name in query:
                return zone
    return 3


def _extract_postcode_outward(address: str) -> str | None:
    """Extract first London postcode outward from address (e.g. E8, SW4)."""
    if not address:
        return None
    match = _POSTCODE_OUTWARD.search(address)
    if match:
        return match.group(1).upper()
    # Fallback: any area+digit pattern that looks like London postcode
    for m in _POSTCODE_SIMPLE.finditer(address):
        outward = m.group(1).upper()
        if outward in POSTCODE_OUTWARD_TO_ZONE:
            return outward
        if re.match(r"^(E|EC|N|NW|SE|SW|W|WC)\d", outward):
            return outward
    return None


def get_zone_from_address(address: str) -> int:
    """Derive TfL zone (1–6) from a full address when not in the listing.

    Uses, in order:
    1. Postcode outward mapping (e.g. E8, SW4) when present in address
    2. Area name matching via search_areas (e.g. 'Hackney', 'Clapham')
    3. Fallback zone 3
    """
    if not address or not str(address).strip():
        return 3

    addr = str(address).strip()

    # 1. Try postcode outward first (most reliable when present)
    outward = _extract_postcode_outward(addr)
    if outward:
        if outward in POSTCODE_OUTWARD_TO_ZONE:
            return POSTCODE_OUTWARD_TO_ZONE[outward]
        # Unknown London outward (e.g. rare variant): default zone 3
        if re.match(r"^(E|EC|N|NW|SE|SW|W|WC)\d", outward, re.IGNORECASE):
            return 3

    # 2. Try area name matching (address may contain "Hackney", "Clapham", etc.)
    areas = search_areas(addr)
    if areas:
        best = areas[0]
        if "zone" in best:
            return best["zone"]
        return get_zone(best.get("name", ""))

    # 3. Fallback
    return 3


def get_location_id(area_name: str) -> str | None:
    if not area_name:
        return None

    query = _normalize(area_name)
    exact_matches = [
        location_id
        for name, location_id in LONDON_AREAS.items()
        if _normalize(name) == query
    ]
    if exact_matches:
        return exact_matches[0]

    partial_matches = [
        (name, location_id)
        for name, location_id in LONDON_AREAS.items()
        if query in _normalize(name) or _normalize(name) in query
    ]
    if partial_matches:
        partial_matches.sort(key=lambda match: len(match[0]))
        return partial_matches[0][1]

    return None


def get_london_borough_areas() -> list[str]:
    """Return area names for London-wide search (borough-level coverage across all of London).

    Deduplicates by location ID so that aliases mapping to the same REGION
    (e.g. "London" and "Central London" both map to REGION^87490) are only
    included once, preventing duplicate requests when iterating per-borough.
    """
    seen_ids: set[str] = set()
    names: list[str] = []
    for name, loc_id in LONDON_AREAS.items():
        if str(loc_id).startswith("REGION^") and loc_id not in seen_ids:
            seen_ids.add(loc_id)
            names.append(name)
    return names


# London-wide Rightmove identifier that returns results (REGION^87490 = London).
# Borough-level IDs (e.g. Camden, Islington) often return "couldn't find the place" from Rightmove.
LONDON_WIDE_LOCATION_ID = "REGION^87490"


def search_areas(query: str) -> list[dict]:
    normalized_query = _normalize(query) if query else ""
    results: list[tuple[float, str, str, int]] = []

    for name, location_id in LONDON_AREAS.items():
        normalized_name = _normalize(name)
        if not normalized_query:
            score = 1.0
        elif normalized_query in normalized_name:
            score = 2.0 + (len(normalized_query) / max(len(normalized_name), 1))
        else:
            score = SequenceMatcher(None, normalized_query, normalized_name).ratio()

        if score >= 0.35:
            zone = get_zone(name)
            results.append((score, name, location_id, zone))

    results.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"name": name, "location_id": location_id, "zone": zone}
        for _, name, location_id, zone in results
    ]
