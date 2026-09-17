"""Payer change schema and reconciled resident coverage seeder."""

from datetime import date, timedelta
from hashlib import sha256
from random import Random
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    func,
    or_,
    select,
    text,
)

from seeding.generators.admissions import FIRST_NAMES, LAST_NAMES, PAYER_NAMES, choose_weighted_payer_type
from seeding.base import BaseSeeder, SeedContext, SeedResult, coverage
from seeding.generators.facilities import facilities

GENERATOR_VERSION = "resident-payer-movement-v2"
EVENT_NAMESPACE = "payer-changes-history-v2"
EPOCH = date(2020, 1, 1)
from data.models.payer_changes import metadata, payer_changes

from seeding.scenarios.coverage import DESTINATIONS


def build_daily_payer_changes(day: date, facility_rows: list[dict]) -> list[dict]:
    """Each stable 90-day resident episode has two chronological coverage changes."""
    rows = []
    for facility in sorted(facility_rows, key=lambda row: row["facility_code"]):
        code = facility["facility_code"]
        fingerprint = int(sha256(code.encode()).hexdigest()[:8], 16)
        cycle, offset = divmod((day - EPOCH).days + fingerprint % 90, 90)
        shift = fingerprint % 40
        for slot in range(8 + fingerprint % 24):
            first = (slot * 7 + shift) % 40
            if offset not in (first, first + 40):
                continue
            identity = f"{EVENT_NAMESPACE}:{code}:{cycle}:{slot}"
            random = Random(identity)
            resident_id = str(uuid5(NAMESPACE_URL, identity))
            periods = Random(f"payer-periods:{resident_id}")
            initial_days, final_days = periods.randint(7, 90), periods.randint(7, 120)
            resident_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            previous = choose_weighted_payer_type(random)
            previous_name = random.choice(PAYER_NAMES[previous])
            for sequence, event_offset in enumerate((first, first + 40)):
                alternatives = [name for name in PAYER_NAMES[previous] if name != previous_name]
                if alternatives and random.random() < 0.2:
                    new, new_name = previous, random.choice(alternatives)
                else:
                    weights = DESTINATIONS[previous]
                    new = random.choices(list(weights), weights=list(weights.values()))[0]
                    new_name = random.choice(PAYER_NAMES[new])
                if event_offset == offset:
                    rows.append(
                        {
                            "change_id": str(uuid5(NAMESPACE_URL, f"{identity}:{sequence}")),
                            "facility_code": code,
                            "resident_id": resident_id,
                            "resident_name": resident_name,
                            "effective_date": day,
                            "previous_payer_start_date": day
                            - timedelta(days=initial_days if sequence == 0 else 40),
                            "new_payer_end_date": day
                            + timedelta(days=40 if sequence == 0 else final_days),
                            "previous_payer_type": previous,
                            "previous_payer_name": previous_name,
                            "new_payer_type": new,
                            "new_payer_name": new_name,
                            "change_category": "Plan only" if previous == new else "Payer type",
                        }
                    )
                previous, previous_name = new, new_name
    return rows


class PayerChangesSeeder(BaseSeeder):
    name = "payer_changes"
    dependencies = ("discharges",)

    def seed(self, context: SeedContext) -> SeedResult:
        from seeding.generators.payer_movement import seed_payers
        return seed_payers(context)

    def validate(self, context, result):
        from data.models.payer_periods import periods
        invalid = context.connection.scalar(select(func.count()).select_from(periods).where(
            periods.c.facility_code.in_(context.facility_codes), periods.c.end_date < periods.c.start_date))
        if invalid:
            raise ValueError('Coverage interval ends must not precede their starts.')
