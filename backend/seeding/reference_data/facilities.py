"""Stable demo facility reference definitions."""
from collections import Counter
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class Market:
    city: str
    portfolio: str
    state: str
    market: str


TEXAS_MARKETS = (
    Market("Dallas", "Lone Star", "TX", "Dallas-Fort Worth"),
    Market("Houston", "Lone Star", "TX", "Greater Houston"),
    Market("San Antonio", "Lone Star", "TX", "South Texas"),
    Market("Austin", "Lone Star", "TX", "Central Texas"),
    Market("Fort Worth", "Lone Star", "TX", "Dallas-Fort Worth"),
    Market("El Paso", "Lone Star", "TX", "West Texas"),
    Market("McAllen", "Lone Star", "TX", "Rio Grande Valley"),
    Market("Corpus Christi", "Lone Star", "TX", "Coastal Bend"),
)

FLORIDA_MARKETS = (
    Market("Tampa", "Sunshine", "FL", "Tampa Bay"),
    Market("Orlando", "Sunshine", "FL", "Central Florida"),
    Market("Jacksonville", "Sunshine", "FL", "Northeast Florida"),
    Market("Miami", "Sunshine", "FL", "South Florida"),
    Market("Fort Myers", "Sunshine", "FL", "Southwest Florida"),
    Market("Tallahassee", "Sunshine", "FL", "Florida Panhandle"),
)

PENNSYLVANIA_MARKETS = (
    Market("Philadelphia", "Keystone", "PA", "Greater Philadelphia"),
    Market("Pittsburgh", "Keystone", "PA", "Western Pennsylvania"),
    Market("Allentown", "Keystone", "PA", "Lehigh Valley"),
)

PORTFOLIOS_BY_STATE = {
    "FL": ("Florida 1", "Florida 2", "Florida 3"),
    "PA": ("Pennsylvania 1",),
    "TX": (
        "Texas 1",
        "Texas 2",
        "Texas 3",
        "Texas 4",
        "Texas 5",
    ),
}

# Balanced assignments keep each operating region within the 5?15 facility range.
MIN_FACILITIES_PER_REGION = 5
MAX_FACILITIES_PER_REGION = 15
REGIONS_BY_PORTFOLIO = {
    "Texas 1": ("Dallas", "Fort Worth", "Denton"),
    "Florida 1": ("Orlando", "Lakeland"),
    "Florida 2": ("Jacksonville", "Tallahassee"),
    "Pennsylvania 1": ("Pennsylvania",),
    "Texas 2": ("Houston", "Galveston", "The Woodlands"),
    "Texas 3": ("San Antonio", "Rio Grande", "Corpus Christi"),
    "Texas 4": ("Austin", "Hill Country", "Waco"),
    "Texas 5": ("El Paso", "Lubbock", "Amarillo"),
    "Florida 3": ("Miami", "Fort Myers"),
}


FACILITY_NAME_PREFIXES = (
    "Alder",
    "Beacon",
    "Brighton",
    "Canyon",
    "Cedar",
    "Cypress",
    "Elmwood",
    "Fairview",
    "Foxbridge",
    "Grandview",
    "Hawthorne",
    "Juniper",
    "Lakewood",
    "Maplewood",
    "Northfield",
    "Oakmont",
    "Pinehurst",
    "Redwood",
    "Silverwood",
    "Stonebridge",
    "Summit",
    "Westbrook",
    "Willow",
)

FACILITY_PROFILES = (
    ("Haven", 118, "Post-acute rehabilitation", "Moderate"),
    ("Grove", 92, "Long-term care", "Low"),
    ("Pointe", 146, "Skilled nursing and rehabilitation", "High"),
    ("Meadows", 104, "Long-term care", "Moderate"),
    ("Harbor", 128, "Post-acute rehabilitation", "High"),
    ("Crest", 86, "Long-term care", "Low"),
    ("View", 112, "Skilled nursing and rehabilitation", "Moderate"),
    ("Bend", 136, "Post-acute rehabilitation", "High"),
    ("Place", 98, "Long-term care", "Moderate"),
    ("Lodge", 122, "Skilled nursing and rehabilitation", "High"),
    ("Terrace", 108, "Long-term care", "Low"),
)



def build_facility_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for sequence in range(1, 254):
        profile_index = (sequence - 1) % len(FACILITY_PROFILES)
        name_prefix_index = (sequence - 1) // len(FACILITY_PROFILES)
        suffix, base_beds, primary_service, acuity_profile = FACILITY_PROFILES[profile_index]
        if sequence <= 164:
            state_sequence = sequence - 1
            market = TEXAS_MARKETS[state_sequence % len(TEXAS_MARKETS)]
        elif sequence <= 240:
            state_sequence = sequence - 165
            market = FLORIDA_MARKETS[state_sequence % len(FLORIDA_MARKETS)]
        else:
            state_sequence = sequence - 241
            market = PENNSYLVANIA_MARKETS[state_sequence % len(PENNSYLVANIA_MARKETS)]

        portfolios = PORTFOLIOS_BY_STATE[market.state]
        portfolio = portfolios[state_sequence % len(portfolios)]
        region = REGIONS_BY_PORTFOLIO[portfolio][
            (state_sequence // len(portfolios)) % len(REGIONS_BY_PORTFOLIO[portfolio])
        ]
        operating_group = f"Aspire {portfolio} Operations"
        opened_year = 1997 + ((name_prefix_index * 3 + profile_index * 2) % 24)

        rows.append(
            {
                "facility_code": f"ASP-{sequence:03d}",
                "name": f"{FACILITY_NAME_PREFIXES[name_prefix_index]} {suffix}",
                "city": market.city,
                "state": market.state,
                "portfolio": portfolio,
                "region": region,
                "market": market.market,
                "operating_group": operating_group,
                "licensed_beds": base_beds + ((name_prefix_index % 4) * 4),
                "primary_service": primary_service,
                "acuity_profile": acuity_profile,
                "operating_maturity": ("Established", "Growth", "Legacy")[sequence % 3],
                "opened_date": date(opened_year, 1, 1),
                "services": {
                    "rehabilitation": primary_service != "Long-term care",
                    "long_term_care": primary_service != "Post-acute rehabilitation",
                    "memory_support": profile_index in (1, 3, 5, 8, 10),
                    "respiratory_care": acuity_profile == "High",
                },
            }
        )

    validate_region_sizes(rows)
    return rows


def validate_region_sizes(rows: list[dict[str, object]]) -> None:
    counts = Counter((row["state"], row["portfolio"], row["region"]) for row in rows)
    invalid = {
        key: count for key, count in counts.items()
        if not MIN_FACILITIES_PER_REGION <= count <= MAX_FACILITIES_PER_REGION
    }
    if invalid:
        raise ValueError(
            f"Each region must contain {MIN_FACILITIES_PER_REGION}?"
            f"{MAX_FACILITIES_PER_REGION} facilities: {invalid}"
        )


