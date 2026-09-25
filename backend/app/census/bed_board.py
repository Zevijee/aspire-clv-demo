"""One facility's beds on the census day, room by room, and who is in each.

Beds come from facility_beds and occupants from bed_assignments, whose rows are
stretches in one bed: a resident is in a bed on day d when a row's in_bed
contains d. Payer, care level and the day's rate come from the census_logs row
covering the same stay that day, with the PDPM rate for skilled payers -- the
same values the Residents tab lists, so the two cannot disagree.

Only one facility is read, so every step is a few hundred rows. The day's
census rows are still found through the range index first and filtered to the
facility after; census_logs has no index on stay or facility.
"""
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import Integer, and_, cast, func, literal, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    bed_assignments as assignments, census_logs as logs, daily_runs, facility_beds as beds,
    payers, pdpm_rate_logs as pdpm, residents)
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations

GENERATOR = 'bed_assignments'


class Occupant(BaseModel):
    resident_id: UUID
    first_name: str
    last_name: str
    gender: str
    admission_date: date
    in_bed_since: date = Field(description='First day in this bed. Later than admission after a move.')
    payer_type: str
    payer_name: str
    is_skilled: bool
    care_level: str
    skilled_day: int | None = Field(description='Day of skilled coverage, for skilled payers only.')
    daily_rate: float


class Bed(BaseModel):
    wing: str
    room: str
    bed: str
    occupant: Occupant | None


class FacilityOption(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str


class BedBoard(BaseModel):
    as_of: date
    census_date: date = Field(description='The latest day with bed assignments on or before `as_of`.')
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    beds: list[Bed] = Field(description='Every licensed bed, by wing, room and bed.')
    waiting: list[Occupant] = Field(description=
        'Residents in the building with no free bed. Empty unless census exceeds licensed beds.')


def facility_options(connection: Connection):
    """Every facility by name, for the picker. The board shows one at a time."""
    return [dict(facility_id=row['facility_id'], facility_name=row['facility_name'], state=row['state'])
        for row in connection.execute(facility_locations(LocationSelection())
            .order_by('facility_name')).mappings()]


def board(connection: Connection, today: date, facility_id: UUID | None):
    census_date = connection.scalar(select(func.max(daily_runs.c.simulation_date)).where(
        daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date <= today))
    if census_date is None:
        raise ApiError('summary_unavailable', 'Bed assignments have not been generated yet. '
            'Run the seeder update, including bed_assignments.', 409)

    locations = connection.execute(facility_locations(LocationSelection())
        .order_by('facility_name')).mappings().all()
    if not locations:
        raise ApiError('not_found', 'There are no facilities.', 404)
    location = next((row for row in locations if row['facility_id'] == facility_id), None)
    if facility_id is not None and location is None:
        raise ApiError('not_found', 'No facility has that ID.', 404)
    location = location or locations[0]
    facility_id = location['facility_id']

    day = literal(census_date)
    census = (select(logs.c.stay_id, logs.c.payer_stay_id, logs.c.payer_id, logs.c.care_level,
            logs.c.admission_date, logs.c.daily_rate)
        .where(logs.c.in_bed.contains(census_date), logs.c.facility_id == facility_id)
        .cte('census').prefix_with('MATERIALIZED'))
    occupants = (select(assignments.c.bed_id, assignments.c.resident_id,
            func.lower(assignments.c.in_bed).label('in_bed_since'),
            residents.c.first_name, residents.c.last_name, residents.c.gender,
            census.c.admission_date, census.c.care_level,
            payers.c.payer_type, payers.c.payer_name, payers.c.is_skilled,
            (pdpm.c.skilled_day + (day - func.lower(pdpm.c.in_effect))).label('skilled_day'),
            func.coalesce(pdpm.c.daily_rate, census.c.daily_rate).label('daily_rate'))
        .select_from(assignments
            .join(census, census.c.stay_id == assignments.c.stay_id)
            .join(residents, residents.c.resident_id == assignments.c.resident_id)
            .join(payers, payers.c.payer_id == census.c.payer_id)
            .outerjoin(pdpm, and_(pdpm.c.payer_stay_id == census.c.payer_stay_id,
                pdpm.c.in_effect.contains(census_date))))
        .where(assignments.c.facility_id == facility_id, assignments.c.in_bed.contains(census_date)))

    def occupant(row):
        return dict(resident_id=row['resident_id'], first_name=row['first_name'],
            last_name=row['last_name'], gender=row['gender'], admission_date=row['admission_date'],
            in_bed_since=row['in_bed_since'], payer_type=row['payer_type'],
            payer_name=row['payer_name'], is_skilled=row['is_skilled'],
            care_level=row['care_level'], skilled_day=row['skilled_day'],
            daily_rate=float(row['daily_rate']))

    by_bed, waiting = {}, []
    for row in connection.execute(occupants).mappings():
        if row['bed_id'] is None:
            waiting.append(occupant(row))
        else:
            by_bed[row['bed_id']] = occupant(row)

    layout = connection.execute(select(beds.c.bed_id, beds.c.wing, beds.c.room, beds.c.bed)
        .where(beds.c.facility_id == facility_id)
        .order_by(beds.c.wing, cast(beds.c.room, Integer), beds.c.bed)).mappings()
    return dict(as_of=today, census_date=census_date, facility_id=facility_id,
        facility_name=location['facility_name'], state=location['state'],
        portfolio=location['portfolio_name'], region=location['region_name'],
        beds=[dict(wing=row['wing'], room=row['room'], bed=row['bed'],
            occupant=by_bed.get(row['bed_id'])) for row in layout],
        waiting=sorted(waiting, key=lambda item: (item['last_name'], item['first_name'])))
