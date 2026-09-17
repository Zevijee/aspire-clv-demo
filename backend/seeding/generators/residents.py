"""Stable demo resident identities, independent of source table persistence."""
from random import Random
from uuid import NAMESPACE_URL, uuid5
from seeding.scenarios.admissions import FIRST_NAMES, LAST_NAMES

VERSION = 'resident-identity-v1'


def arrival_resident(admission_key):
    # Preserve the existing scenario's keys; changing the loading order must not
    # rename existing people. Readmission planning can select a prior resident.
    random = Random(f'admission-demographics:{admission_key}')
    return dict(resident_id=str(uuid5(NAMESPACE_URL, f'aspire-resident:{admission_key}')),
        display_name=f'{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}')


def opening_resident(resident_key):
    random = Random(resident_key)
    return dict(resident_id=resident_key,
        display_name=f'{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}')
