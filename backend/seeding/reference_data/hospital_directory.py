"""Regional demo hospitals and deterministic receiving-facility relationships."""

from functools import lru_cache
from math import sin, pi
from random import Random

from seeding.reference_data.facilities import build_facility_rows

_FACILITIES = build_facility_rows()
_LOCATIONS = sorted({(str(row['state']), str(row['portfolio']), str(row['region'])) for row in _FACILITIES})
_SUFFIXES = (
    'General Hospital', 'Medical Center', 'Regional Hospital', 'Memorial Hospital',
    'University Hospital', 'Community Hospital', 'Mercy Hospital', 'Baptist Hospital',
    'Methodist Hospital', 'Central Hospital', 'Valley Hospital', 'North Hospital',
    'South Hospital', 'East Hospital', 'West Hospital', 'Park Hospital',
    'Lake Hospital', 'Riverside Hospital', 'Summit Hospital', 'Pioneer Hospital',
)
HOSPITAL_DIRECTORY = {
    f'{region} {suffix}': {'state': state, 'portfolio': portfolio, 'region': region}
    for state, portfolio, region in _LOCATIONS
    for suffix in _SUFFIXES[:Random(f'hospital-count:{state}:{portfolio}:{region}').randint(10, 20)]
}


@lru_cache(maxsize=1024)
def _regional_hospitals(state, portfolio, region):
    names = tuple(name for name, location in HOSPITAL_DIRECTORY.items()
                  if (location['state'], location['portfolio'], location['region']) == (state, portfolio, region))
    if not names:
        raise ValueError(f'No hospitals for facility hierarchy: {state} / {portfolio} / {region}')
    return names


def hospital_names_for_facility(facility: dict) -> tuple[str, ...]:
    return _regional_hospitals(facility['state'], facility['portfolio'], facility['region'])


@lru_cache(maxsize=2048)
def _hospital_profile(hospital):
    profile = Random(f'hospital-profile:{hospital}')
    return profile.random() * 2 * pi, profile.randint(540, 1080)


@lru_cache(maxsize=None)
def facility_hospital_partners(code: str) -> tuple[str, ...]:
    facility = next(row for row in _FACILITIES if row['facility_code'] == code)
    regional = hospital_names_for_facility(facility)
    peers = [row for row in _FACILITIES if all(row[key] == facility[key] for key in ('state', 'portfolio', 'region'))]
    position = next(index for index, row in enumerate(peers) if row['facility_code'] == code)
    random = Random(f'hospital-partners:{code}')
    # Four rotating partners cover every regional hospital, even in five-facility regions.
    partners = list(dict.fromkeys(regional[(position * 4 + index) % len(regional)] for index in range(4)))
    target = random.randint(5, min(9, len(regional)))
    remaining = [name for name in regional if name not in partners]
    random.shuffle(remaining)
    return tuple(partners + remaining[:target - len(partners)])


def choose_referring_hospital(facility: dict, admission_id: str, day) -> str:
    partners = facility_hospital_partners(facility['facility_code'])
    regional = hospital_names_for_facility(facility)
    weights = []
    for hospital in partners:
        phase, cycle = _hospital_profile(hospital)
        trend = 1 + 0.75 * sin(2 * pi * day.toordinal() / cycle + phase)
        # A few large referral sources and a long tail of smaller hospitals.
        weights.append(trend / (regional.index(hospital) + 1) ** 1.25)
    return Random(f'hospital-referral:{admission_id}').choices(partners, weights=weights, k=1)[0]
