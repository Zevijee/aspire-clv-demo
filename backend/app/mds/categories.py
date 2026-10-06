"""Current PDPM residents counted by PDPM category, per facility.

The same residents as the Current Medicare PDPM report -- Federal Medicare and
Managed Medicare PDPM in a bed on the census day -- read through its _current
query, so the counts cannot disagree with its Residents tab. Facility rows carry
counts only; the page sums them for any parent scope.

Primary diagnosis is the PT/OT clinical category, the first letter of the PDPM
code: four functional score bands per category, so A-D, E-H, I-L and M-P.
"""
from datetime import date

from pydantic import BaseModel
from sqlalchemy import Date, case, func, literal, select
from sqlalchemy.engine import Connection

from shared.database.schema import pdpm_assessments as assessments
from ..common.locations import LocationSelection, facility_locations
from .residents import _current
from .service import census_day

# Field -> the first letters of the PDPM code in that clinical category.
PRIMARY_DIAGNOSIS = {
    'major_joint': 'ABCD',
    'ortho': 'EFGH',
    'medical_management': 'IJKL',
    'acute_neuro': 'MNOP',
}


class PrimaryDiagnosis(BaseModel):
    major_joint: int
    ortho: int
    acute_neuro: int
    medical_management: int


class FacilityCategories(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    primary_diagnosis: PrimaryDiagnosis


class Categories(BaseModel):
    census_date: date
    items: list[FacilityCategories]


def categories(connection: Connection, today: date):
    census_date = census_day(connection, today)
    current = _current(literal(census_date, Date))
    letter = func.substr(assessments.c.pdpm_code, 1, 1)
    category = case(*((letter.in_(list(letters)), field) for field, letters in PRIMARY_DIAGNOSIS.items()))
    counts = {}
    for row in connection.execute(select(current.c.facility_id, category.label('category'), func.count())
            .select_from(current.join(assessments, assessments.c.payer_stay_id == current.c.payer_stay_id))
            .group_by(current.c.facility_id, category)):
        counts.setdefault(row.facility_id, dict.fromkeys(PRIMARY_DIAGNOSIS, 0))[row.category] = row[2]
    # Every facility, so one with no PDPM residents reads as zeros in its parent.
    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            primary_diagnosis=counts.get(location['facility_id'], dict.fromkeys(PRIMARY_DIAGNOSIS, 0)))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(census_date=census_date, items=sorted(items,
        key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))
