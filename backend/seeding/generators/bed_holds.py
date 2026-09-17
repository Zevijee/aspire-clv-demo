"""Deterministic demo reserved-bed counts, including zero-activity dates."""
from random import Random
from sqlalchemy import select, func, delete
from data.writers.core import write_rows
from data.models.bed_holds import bed_holds
from data.models.stays import census
from data.models.facilities import facilities
from seeding.base import BaseSeeder, SeedResult


class BedHoldsSeeder(BaseSeeder):
    name = "bed_holds"
    dependencies = ("discharges",)

    def seed(self, context):
        from seeding.base import SeedWindow
        from data.models.seed_tracking import coverage
        from datetime import timedelta
        window = context.replace_window if context.rebuild and context.replace_window else context.window
        if not context.rebuild:
            completed = set(context.connection.scalars(select(coverage.c.seed_date).where(
                coverage.c.dataset == context.dataset_key(self.name))))
            missing = [window.start_date + timedelta(days=i) for i in range(window.days)
                if window.start_date + timedelta(days=i) not in completed]
            starts = missing + ([context.changed_from] if context.changed_from else [])
            if not starts:
                return SeedResult(self.name,0,0)
            window = SeedWindow(min(starts),window.end_date)
        # The movement generator publishes daily census alongside stays/discharges.
        source = context.connection.execute(select(census.c.facility_code, census.c.census_date,
            census.c.closing_census, facilities.c.licensed_beds).join(facilities,
            facilities.c.facility_code == census.c.facility_code).where(
            census.c.census_date.between(window.start_date, window.end_date),
            census.c.facility_code.in_(context.facility_codes))).mappings()
        rows = []
        for row in source:
            available = max(0, row["licensed_beds"] - row["closing_census"])
            count = min(available, Random(f'bed-holds-v1:{row["facility_code"]}:{row["census_date"]}').choices(
                [0, 1, 2, 3, 4], weights=[45, 30, 15, 8, 2])[0])
            rows.append(dict(facility_code=row["facility_code"], census_date=row["census_date"], bed_holds=count))
        if context.rebuild:
            context.connection.execute(delete(bed_holds).where(bed_holds.c.facility_code.in_(context.facility_codes),
                bed_holds.c.census_date.between(window.start_date, window.end_date)))
        changed = write_rows(context.connection, bed_holds, rows, batch_size=context.batch_size).changed
        from seeding.state.store import mark_coverage
        mark_coverage(context, self.name, window, {row['census_date']: row['bed_holds'] for row in rows})
        return SeedResult(self.name, len(rows), changed, window.start_date if changed else None)

    def validate(self, context, result):
        invalid = context.connection.scalar(select(func.count()).select_from(bed_holds.join(census,
            (bed_holds.c.facility_code == census.c.facility_code) &
            (bed_holds.c.census_date == census.c.census_date)).join(facilities,
            facilities.c.facility_code == bed_holds.c.facility_code)).where(
            bed_holds.c.facility_code.in_(context.facility_codes),
            bed_holds.c.bed_holds + census.c.closing_census > facilities.c.licensed_beds))
        if invalid:
            raise ValueError("Reserved beds plus occupied beds exceed capacity.")
