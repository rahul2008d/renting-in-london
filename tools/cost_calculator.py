from __future__ import annotations

import json
from strands import tool


# London council tax annual amounts by band (2025/26 approximate
# averages across London boroughs — actual varies by borough)
COUNCIL_TAX_ANNUAL: dict[str, int] = {
    "A": 1050,
    "B": 1225,
    "C": 1400,
    "D": 1575,
    "E": 1925,
    "F": 2275,
    "G": 2625,
    "H": 3150,
}

# Estimated monthly energy costs by EPC rating (typical 2-bed flat)
ENERGY_MONTHLY_BY_EPC: dict[str, int] = {
    "A": 60,
    "B": 80,
    "C": 110,
    "D": 150,
    "E": 200,
    "F": 250,
    "G": 300,
}

# Monthly Oyster/commute cost estimates by zone
COMMUTE_MONTHLY_BY_ZONE: dict[int, int] = {
    1: 175,   # Zone 1 travelcard
    2: 175,   # Zone 1-2
    3: 205,   # Zone 1-3
    4: 250,   # Zone 1-4
    5: 295,   # Zone 1-5
    6: 320,   # Zone 1-6
}

# Driving cost estimate (petrol + parking + congestion if applicable)
DRIVING_MONTHLY_BY_ZONE: dict[int, int] = {
    1: 400,   # Congestion charge £15/day × 20 days + parking
    2: 200,   # Parking + petrol
    3: 150,   # Petrol mainly
    4: 180,   # More petrol, longer distances
    5: 220,   # Long distance commute
    6: 250,
}


def _safe_int(val: object, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


@tool
def calculate_total_monthly_cost(
    rent_pcm: int,
    council_tax_band: str = "",
    epc_rating: str = "",
    zone: int = 3,
    service_charge_monthly: int = 0,
    commute_days_per_week: int = 3,
    has_car: bool = True,
) -> str:
    """Calculate estimated total monthly living cost for a rental property.

    Args:
        rent_pcm: Monthly rent in GBP.
        council_tax_band: Council tax band A-H. Empty = estimate from zone.
        epc_rating: EPC rating A-G. Empty = assume D.
        zone: TfL zone 1-6 for commute cost estimate.
        service_charge_monthly: Monthly service charge if known (0 if unknown).
        commute_days_per_week: Days commuting to office per week.
        has_car: Whether the tenant drives (affects congestion charge calc).

    Returns:
        JSON string with itemised monthly cost breakdown and total.
    """
    # Rent
    rent = _safe_int(rent_pcm, 0)
    if rent <= 0:
        return json.dumps({"error": "rent_pcm must be positive."})

    # Council tax
    ct_band = council_tax_band.strip().upper()[:1] if council_tax_band else ""
    if ct_band and ct_band in COUNCIL_TAX_ANNUAL:
        council_tax_annual = COUNCIL_TAX_ANNUAL[ct_band]
        ct_source = f"Band {ct_band}"
    else:
        # Estimate: Zone 1-2 tend to be Band D-E, Zone 3-4 Band C-D
        estimated_band = {1: "D", 2: "D", 3: "C", 4: "C", 5: "B", 6: "B"}
        band = estimated_band.get(zone, "C")
        council_tax_annual = COUNCIL_TAX_ANNUAL[band]
        ct_source = f"Estimated Band {band} (not listed — verify with agent)"
    council_tax_monthly = round(council_tax_annual / 12)

    # Energy
    epc = epc_rating.strip().upper()[:1] if epc_rating else ""
    if epc and epc in ENERGY_MONTHLY_BY_EPC:
        energy_monthly = ENERGY_MONTHLY_BY_EPC[epc]
        energy_source = f"EPC {epc}"
    else:
        energy_monthly = ENERGY_MONTHLY_BY_EPC["D"]
        energy_source = "Estimated (EPC not listed — assume D)"

    # Service charge
    service_charge = _safe_int(service_charge_monthly, 0)

    # Commute cost (public transport)
    zone_capped = max(1, min(6, zone))
    commute_full_month = COMMUTE_MONTHLY_BY_ZONE.get(zone_capped, 205)
    # Scale by days per week (5 days = full travelcard, fewer = pay as you go)
    if commute_days_per_week >= 5:
        commute_monthly = commute_full_month
    else:
        # Pay as you go is roughly 60-70% of travelcard cost per trip
        daily_cost = (commute_full_month / 20) * 0.7
        commute_monthly = round(daily_cost * commute_days_per_week * 4.33)
    commute_source = f"Zone 1-{zone_capped}, {commute_days_per_week} days/week"

    # Car costs (if applicable)
    car_monthly = 0
    car_source = "No car"
    if has_car:
        car_monthly = DRIVING_MONTHLY_BY_ZONE.get(zone_capped, 150)
        if zone_capped == 1:
            car_source = f"Zone {zone_capped} — includes congestion charge estimate"
        else:
            car_source = f"Zone {zone_capped} — petrol + parking estimate"

    # Broadband + water (fixed estimate for London)
    utilities_monthly = 70  # ~£35 broadband + ~£35 water
    utilities_source = "Broadband + water estimate"

    # Total
    total = (
        rent
        + council_tax_monthly
        + energy_monthly
        + service_charge
        + commute_monthly
        + car_monthly
        + utilities_monthly
    )

    breakdown = {
        "rent": {"amount": rent, "note": "Monthly rent"},
        "council_tax": {"amount": council_tax_monthly, "note": ct_source},
        "energy": {"amount": energy_monthly, "note": energy_source},
        "service_charge": {"amount": service_charge, "note": "From listing" if service_charge > 0 else "Not listed — verify"},
        "commute": {"amount": commute_monthly, "note": commute_source},
        "car": {"amount": car_monthly, "note": car_source},
        "utilities": {"amount": utilities_monthly, "note": utilities_source},
    }

    # Annual equivalent
    annual_total = total * 12

    # Affordability context
    take_home_couple_estimate = 5500  # Rough estimate for context
    rent_to_income_pct = round((rent / take_home_couple_estimate) * 100, 1)

    return json.dumps({
        "total_monthly": total,
        "annual_total": annual_total,
        "breakdown": breakdown,
        "rent_to_income_note": f"Rent alone is ~{rent_to_income_pct}% of an estimated £{take_home_couple_estimate} couple take-home (adjust to your actual income)",
        "summary": f"£{total}/month total (rent £{rent} + £{total - rent} running costs)",
    })
