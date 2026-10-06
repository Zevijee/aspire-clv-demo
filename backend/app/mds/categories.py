"""Current PDPM residents counted by PDPM category, per facility.

The same residents as the Current Medicare PDPM report -- Federal Medicare and
Managed Medicare PDPM in a bed on the census day -- read through its _current
query, so the counts cannot disagree with its Residents tab. Facility rows carry
counts only; the page sums them for any parent scope.

Primary diagnosis is the PT/OT clinical category, the first letter of the PDPM
code: four functional score bands per category, so A-D, E-H, I-L and M-P.

PT/OT is the function score band of the same letter, its position within its
category: A, E, I and M are 0-5, then 6-9, 10-23 and 24. The generator writes the
letter as category * 4 + band, so both counts come from the one letter.

SLP is the second letter, A-L: the number of speech conditions (acute neuro,
SLP comorbidity, cognitive impairment; 0-3) times three, plus the number of
swallowing needs (mechanically altered diet, swallowing disorder; 0-2). Each
resident has exactly one, so these sum to the residents.

Nursing is the nursing function score band, 0-5, 6-14 or 15-16, from the score
stored on the assessment: the nursing letter alone cannot place Extensive
Services (0-14) or Behavioral (11-16), which span two bands.

NTA is the fourth letter, the non-therapy ancillary comorbidity points band:
F 0, E 1-2, D 3-5, C 6-8, B 9-11, A 12 or more.

Depression is a yes / no flag on the assessment: the nursing letter decides it
for special care and clinically complex groups, and says nothing for the rest.

A resident is only counted in a category once their code is available, on or
after its coded_date: in the first days of a Medicare period it has not been
assessed and coded yet. Those residents are counted in no_score instead, so
the categories and no_score together make up the residents.

Speech comorbidity counts residents with each SLP condition: cognitive
impairment, an acute neuro primary diagnosis, a mechanically altered diet and a
swallowing disorder. Unlike the two above they overlap -- one resident can have
several -- so they never sum to the residents. They are flags on the assessment
rather than letters, because the SLP letter says how many conditions, not which.
"""
from datetime import date

from pydantic import BaseModel, create_model
from sqlalchemy import Date, and_, func, literal, select
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
# Field -> the function score band, in letter order within every category.
PT_OT = ('score_0_5', 'score_6_9', 'score_10_23', 'score_24')
# Fields in SLP letter order, A-L: letter index = speech * 3 + swallowing.
SLP = tuple(f'speech_{speech}_swallowing_{swallowing}' for speech in range(4) for swallowing in range(3))
# Field -> the nursing function score range it counts, inclusive.
NURSING = {'score_0_5': (0, 5), 'score_6_14': (6, 14), 'score_15_16': (15, 16)}
# Field -> the NTA letter for that points band, fewest points first.
NTA = {'points_0': 'F', 'points_1_2': 'E', 'points_3_5': 'D', 'points_6_8': 'C', 'points_9_11': 'B',
    'points_12_plus': 'A'}
# Field -> the assessment flag it counts.
SPEECH = {
    'cognitive_impairment': assessments.c.cognitive_impairment,
    'acute_neuro': assessments.c.acute_neuro,
    'mechanically_altered_diet': assessments.c.mechanically_altered_diet,
    'swallowing_disorder': assessments.c.swallowing_disorder,
}


class PrimaryDiagnosis(BaseModel):
    major_joint: int
    ortho: int
    acute_neuro: int
    medical_management: int


class PtOt(BaseModel):
    score_0_5: int
    score_6_9: int
    score_10_23: int
    score_24: int


class Speech(BaseModel):
    cognitive_impairment: int
    acute_neuro: int
    mechanically_altered_diet: int
    swallowing_disorder: int


class Depression(BaseModel):
    yes: int
    no: int


class Nursing(BaseModel):
    score_0_5: int
    score_6_14: int
    score_15_16: int


Nta = create_model('Nta', **{field: (int, ...) for field in NTA})
Slp = create_model('Slp', **{field: (int, ...) for field in SLP})


class FacilityCategories(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    primary_diagnosis: PrimaryDiagnosis
    pt_ot: PtOt
    slp: Slp
    nursing: Nursing
    nta: Nta
    depression: Depression
    speech: Speech
    # PDPM residents whose code is not available yet on the census day.
    no_score: int
    # Their days since admission, summed, for an average at any scope.
    no_score_days: int


class Categories(BaseModel):
    census_date: date
    items: list[FacilityCategories]


def categories(connection: Connection, today: date):
    census_date = census_day(connection, today)
    day = literal(census_date, Date)
    current = _current(day)
    letter = func.substr(assessments.c.pdpm_code, 1, 1)
    slp_letter = func.substr(assessments.c.pdpm_code, 2, 1)
    diagnosis_of = {code: field for field, letters in PRIMARY_DIAGNOSIS.items() for code in letters}
    empty = lambda: dict(primary_diagnosis=dict.fromkeys(PRIMARY_DIAGNOSIS, 0), pt_ot=dict.fromkeys(PT_OT, 0),
        slp=dict.fromkeys(SLP, 0), nursing=dict.fromkeys(NURSING, 0), nta=dict.fromkeys(NTA, 0),
        depression=dict(yes=0, no=0), speech=dict.fromkeys(SPEECH, 0), no_score=0,
        no_score_days=0)
    counts = {}
    # One row per facility, PT/OT letter and SLP letter; the three letter
    # breakdowns are read from the letters here, the nursing bands and speech
    # flags counted beside. A code not yet available joins as nulls: one row per
    # facility with no letters, which is its no_score count.
    score = assessments.c.nursing_function_score
    nta_letter = func.substr(assessments.c.pdpm_code, 4, 1)
    for facility_id, code, slp_code, residents, days, *flagged in connection.execute(select(
                current.c.facility_id, letter, slp_letter, func.count(), func.sum(day - current.c.admission_date),
                *(func.count().filter(score.between(low, high)) for low, high in NURSING.values()),
                *(func.count().filter(nta_letter == code) for code in NTA.values()),
                func.count().filter(assessments.c.depression),
                *(func.count().filter(flag) for flag in SPEECH.values()))
            .select_from(current.outerjoin(assessments, and_(
                assessments.c.payer_stay_id == current.c.payer_stay_id, assessments.c.coded_date <= day)))
            .group_by(current.c.facility_id, letter, slp_letter)):
        facility = counts.setdefault(facility_id, empty())
        if code is None:
            facility['no_score'] += residents
            facility['no_score_days'] += days
            continue
        if code not in diagnosis_of:
            continue
        for field, residents_in in zip(NURSING, flagged[:len(NURSING)]):
            facility['nursing'][field] += residents_in
        for field, residents_in in zip(NTA, flagged[len(NURSING):len(NURSING) + len(NTA)]):
            facility['nta'][field] += residents_in
        depressed = flagged[len(NURSING) + len(NTA)]
        facility['depression']['yes'] += depressed
        facility['depression']['no'] += residents - depressed
        for field, residents_with in zip(SPEECH, flagged[len(NURSING) + len(NTA) + 1:]):
            facility['speech'][field] += residents_with
        facility['primary_diagnosis'][diagnosis_of[code]] += residents
        facility['pt_ot'][PT_OT[(ord(code) - ord('A')) % 4]] += residents
        facility['slp'][SLP[ord(slp_code) - ord('A')]] += residents
    # Every facility, so one with no PDPM residents reads as zeros in its parent.
    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            **counts.get(location['facility_id'], empty()))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(census_date=census_date, items=sorted(items,
        key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))
