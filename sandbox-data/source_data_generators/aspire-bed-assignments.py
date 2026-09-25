"""Rooms and beds for every facility, and which stay occupied which bed.

Run: python manage.py facility_beds --regenerate
     python manage.py bed_assignments --regenerate
Bed assignments are also rebuilt by every seed and update, after the day's
simulation.

Two tables, for the Bed Board:

- facility_beds: reference data, one row per licensed bed, from each facility's
  bed count. Beds are split into wings of about WING_BEDS, and each wing into
  semi-private rooms (beds A and B) with a PRIVATE_SHARE of private rooms.
- bed_assignments: every stay replayed in date order per facility. A new
  resident takes a free bed in a semi-private room already holding their own
  gender, then an empty room, and only then a room with the other gender.
  Ties are broken by a draw seeded per facility, so open beds scatter across
  the building rather than collecting at its far end.

Both are invented here, like care levels: nothing in the simulation reads them
back, so changing any rule below needs only these rebuilds.
"""
from random import Random

from psycopg import sql
from psycopg.types.range import Range
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator

SEED = 42
WING_BEDS = 32
PRIVATE_SHARE = 0.12
WINGS = 'ABCDEFGHIJ'


class FacilityBedGenerator(BaseGenerator):
    name = 'facility_beds'
    table = schema.facility_beds
    depends_on = ('facilities',)

    def prepare_sources(self, connection):
        self._facilities = self.read_rows(connection, select(
            self.facilities.c.facility_id, self.facilities.c.beds)
            .order_by(self.facilities.c.facility_id))

    def expected_rows(self):
        return sum(facility['beds'] for facility in self._facilities)

    @staticmethod
    def layout(facility_id, beds):
        """(wing, room, bed) for each licensed bed, in board order."""
        rng = Random(BaseGenerator.source_id('bed-layout', SEED, str(facility_id)).int)
        wings = max(1, round(beds / WING_BEDS))
        rows = []
        for index in range(wings):
            wing_beds = beds // wings + (index < beds % wings)
            private = round(wing_beds * PRIVATE_SHARE)
            # Whatever is not private pairs into semi-private rooms.
            if (wing_beds - private) % 2:
                private += 1
            sizes = [1] * private + [2] * ((wing_beds - private) // 2)
            rng.shuffle(sizes)
            for number, size in enumerate(sizes, start=1):
                room = str((index + 1) * 100 + number)
                rows.extend((WINGS[index], room, bed) for bed in 'AB'[:size])
        return rows

    def generate(self):
        for facility in self._facilities:
            facility_id = facility['facility_id']
            for wing, room, bed in self.layout(facility_id, facility['beds']):
                yield dict(bed_id=self.source_id('facility-bed', SEED, str(facility_id), room, bed),
                    facility_id=facility_id, wing=wing, room=room, bed=bed)


class _Facility:
    """The beds of one facility while its stays are replayed."""

    def __init__(self, facility_id, beds):
        self.rng = Random(BaseGenerator.source_id('bed-assignment', SEED, str(facility_id)).int)
        self.room_of = {bed['bed_id']: bed['room'] for bed in beds}
        self.room_beds = {}
        for bed in beds:
            self.room_beds.setdefault(bed['room'], []).append(bed['bed_id'])
        # Gender of whoever holds each bed; absent when free.
        self.holder = {}
        # Rooms with at least one free bed. Walked in sorted order, so the draw
        # is reproducible.
        self.open_rooms = set(self.room_beds)

    def take(self, gender):
        """A free bed for this gender, or None when the facility is full."""
        same, empty, other = [], [], []
        for room in sorted(self.open_rooms):
            beds = self.room_beds[room]
            held = [self.holder[bed] for bed in beds if bed in self.holder]
            free = [bed for bed in beds if bed not in self.holder]
            if not held:
                empty.extend(free)
            elif held[0] == gender:
                same.extend(free)
            else:
                other.extend(free)
        for tier in (same, empty, other):
            if tier:
                bed = self.rng.choice(tier)
                self.holder[bed] = gender
                room = self.room_of[bed]
                if all(each in self.holder for each in self.room_beds[room]):
                    self.open_rooms.discard(room)
                return bed
        return None

    def free(self, bed):
        del self.holder[bed]
        self.open_rooms.add(self.room_of[bed])


def assign(facility_id, beds, stays):
    """Replay one facility's stays in date order and yield bed_assignments rows.

    On each date, discharges free their beds first, then residents already
    waiting are seated, oldest first, then the day's admissions.
    """
    building = _Facility(facility_id, beds)
    admissions, discharges = {}, {}
    for stay in stays:
        admissions.setdefault(stay['admission_date'], []).append(stay)
        if stay['discharge_date'] is not None:
            discharges.setdefault(stay['discharge_date'], []).append(stay)
    # stay_id -> (stay, move, bed_id or None, since)
    current, waiting = {}, []

    def close(stay, until):
        _, move, bed, since = current.pop(stay['stay_id'])
        return dict(stay_id=stay['stay_id'], move=move, resident_id=stay['resident_id'],
            facility_id=facility_id, bed_id=bed, in_bed=Range(since, until, '[)'))

    def seat(stay, day, move):
        bed = building.take(stay['gender'])
        current[stay['stay_id']] = (stay, move, bed, day)
        if bed is None:
            waiting.append(stay)

    for day in sorted(admissions.keys() | discharges.keys()):
        for stay in discharges.get(day, ()):
            bed = current[stay['stay_id']][2]
            if bed is None:
                waiting.remove(stay)
            else:
                building.free(bed)
            yield close(stay, day)
        while waiting and building.open_rooms:
            stay = waiting.pop(0)
            move = current[stay['stay_id']][1]
            yield close(stay, day)
            seat(stay, day, move + 1)
        for stay in admissions.get(day, ()):
            seat(stay, day, 1)
    for stay in [entry[0] for entry in current.values()]:
        yield close(stay, None)


class BedAssignmentGenerator(BaseGenerator):
    name = 'bed_assignments'
    table = schema.bed_assignments
    depends_on = ('res_stays', 'facility_beds')
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        beds = schema.facility_beds
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before assigning beds.')
        laid_out = select(beds.c.facility_id, func.count().label('beds')).group_by(
            beds.c.facility_id).subquery()
        mismatched = connection.scalar(select(func.count()).select_from(self.facilities.outerjoin(
            laid_out, laid_out.c.facility_id == self.facilities.c.facility_id))
            .where(func.coalesce(laid_out.c.beds, 0) != self.facilities.c.beds))
        if mismatched:
            raise ValueError(f'{mismatched:,} facilities have a bed count that differs from their '
                'room layout. Run python manage.py facility_beds --regenerate first.')
        self._beds = {}
        for bed in self.read_rows(connection, select(beds.c.bed_id, beds.c.facility_id, beds.c.room)
                .order_by(beds.c.facility_id, beds.c.wing, beds.c.room, beds.c.bed)):
            self._beds.setdefault(bed['facility_id'], []).append(bed)
        stays = self.res_stays
        self._stays = {}
        for stay in self.read_rows(connection, select(stays.c.stay_id, stays.c.resident_id,
                stays.c.facility_id, stays.c.admission_date, stays.c.discharge_date,
                self.residents.c.gender)
                .join(self.residents, self.residents.c.resident_id == stays.c.resident_id)
                .where(stays.c.admission_date <= through)
                .order_by(stays.c.facility_id, stays.c.admission_date, stays.c.stay_id)):
            self._stays.setdefault(stay['facility_id'], []).append(stay)

    def generate(self):
        for facility_id, stays in self._stays.items():
            yield from assign(facility_id, self._beds.get(facility_id, []), stays)

    def write_generated(self, connection):
        """Replace every row. Discharges close stays after the fact, and a
        different discharge frees a bed for someone else, so any row may change."""
        driver = connection.connection.driver_connection
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(
            self._table_identifier(self.table)).as_string(driver))
        return self.write_rows(connection, self.generate())


GENERATORS = (FacilityBedGenerator, BedAssignmentGenerator)


class DailyBedAssignments(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is the rows
    starting that day."""
    name = 'bed_assignments'
    table = schema.bed_assignments
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = BedAssignmentGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        starts = dict(connection.execute(select(func.lower(self.table.c.in_bed), func.count())
            .where(func.lower(self.table.c.in_bed).in_(days))
            .group_by(func.lower(self.table.c.in_bed))).all())
        return {day: {self.table.name: starts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyBedAssignments,)
