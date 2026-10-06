"""PDPM Worksheet: one row per Medicare PDPM stay -- a Federal Medicare or
Managed Medicare PDPM payer period on a PDPM contract -- that started in the
chosen date range, with cells people fill in -- PT/OT, SLP, nursing and NTA
components and the projected HIPPS -- and a log of every entry and reply. The
final HIPPS is not entered: it is the coded assessment's own code.

Rows include stays that have since ended; Active says whether the Medicare
stay is still running on the latest census day -- a resident can stay in the
building on another payer after it ends. ARD and MDS due
date come from the assessment: the 5-day assessment must be completed within 14
days of its ARD, and reads Complete once its code is available by the latest
census day.

Entries are append-only (pdpm_worksheet_entries). A cell shows its latest set
entry; NTA shows the diagnoses added and not since removed, with their points
summed into the NTA band. Every entry can be replied to. Reading builds the
cells from the log; writing validates the cell and value here, so the table
holds only values this module knows.
"""
import json
from typing import Literal
import re
from datetime import date, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, case, cast, func, insert, literal, or_, select
from sqlalchemy.engine import Connection

from shared import pdpm as pdpm_rates
from shared.database.schema import (
    facilities, facility_payer_rates as contracts, payers, pdpm_assessments as assessments,
    pdpm_worksheet_entries as entries, portfolios, regions, res_payer_stays as periods, res_stays as stays,
    residents)
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery
from .service import GROUP_LABELS, MEDICARE, census_day

# Days from the ARD to the MDS completion deadline.
MDS_DUE_DAYS = 14
# The HIPPS assessment indicator for the 5-day PPS assessment.
FIVE_DAY_INDICATOR = '1'
# The longest range of stay starts one request may ask for.
MAX_RANGE_DAYS = 3660

YES_NO = [dict(value='Yes', label='Yes'), dict(value='No', label='No')]
PT_OT_CATEGORIES = ['Major Joint Replacement or Spinal Surgery', 'Other Orthopedic',
    'Medical Management', 'Non-Orthopedic Surgery and Acute Neurologic']
NURSING_CATEGORIES = ['Extensive Services', 'Special Care High', 'Special Care Low', 'Clinically Complex',
    'Behavioral Symptoms and Cognitive Performance', 'Reduced Physical Function']
# The PDPM NTA comorbidities and their points, as CMS scores them. The demo's
# reference list: id -> (label, points).
NTA_CONDITIONS = {
    'hiv_aids': ('HIV/AIDS', 8),
    'parenteral_high': ('Parenteral IV feeding: level high', 7),
    'iv_medication': ('IV medication (post-admit)', 5),
    'ventilator': ('Ventilator or respirator (post-admit)', 4),
    'parenteral_low': ('Parenteral IV feeding: level low', 3),
    'lung_transplant': ('Lung transplant status', 3),
    'transfusion': ('Transfusion (post-admit)', 2),
    'organ_transplant': ('Major organ transplant status, except lung', 2),
    'multiple_sclerosis': ('Multiple sclerosis', 2),
    'opportunistic_infections': ('Opportunistic infections', 2),
    'chronic_lung': ('Asthma, COPD, chronic lung disease', 2),
    'bone_joint_infection': ('Bone, joint or muscle infection or necrosis, except aseptic necrosis', 2),
    'chronic_myeloid_leukemia': ('Chronic myeloid leukemia', 2),
    'wound_infection': ('Wound infection', 2),
    'diabetes': ('Diabetes mellitus', 2),
    'endocarditis': ('Endocarditis', 1),
    'immune_disorders': ('Immune disorders', 1),
    'end_stage_liver': ('End-stage liver disease', 1),
    'diabetic_foot_ulcer': ('Diabetic foot ulcer', 1),
    'narcolepsy': ('Narcolepsy and cataplexy', 1),
    'cystic_fibrosis': ('Cystic fibrosis', 1),
    'tracheostomy': ('Tracheostomy care (post-admit)', 1),
    'mdro': ('Multi-drug resistant organism', 1),
    'isolation': ('Isolation or quarantine for active infectious disease (post-admit)', 1),
    'hereditary_metabolic': ('Specified hereditary metabolic or immune disorders', 1),
    'morbid_obesity': ('Morbid obesity', 1),
    'radiation': ('Radiation (post-admit)', 1),
    'pressure_ulcer_4': ('Unhealed pressure ulcer, stage 4', 1),
    'psoriatic_arthropathy': ('Psoriatic arthropathy and systemic sclerosis', 1),
    'chronic_pancreatitis': ('Chronic pancreatitis', 1),
    'proliferative_retinopathy': ('Proliferative diabetic retinopathy and vitreous hemorrhage', 1),
    'foot_infection': ('Foot infection or other open lesion on foot', 1),
    'implant_complications': ('Complications of specified implanted device or graft', 1),
    'intermittent_catheter': ('Intermittent catheterization', 1),
    'inflammatory_bowel': ('Inflammatory bowel disease', 1),
    'aseptic_necrosis': ('Aseptic necrosis of bone', 1),
    'suctioning': ('Suctioning (post-admit)', 1),
    'cardio_respiratory_failure': ('Cardio-respiratory failure and shock', 1),
    'myelodysplastic': ('Myelodysplastic syndromes and myelofibrosis', 1),
    'lupus': ('Lupus, other connective tissue disorders, inflammatory spondylopathies', 1),
    'diabetic_retinopathy': ('Diabetic retinopathy, except proliferative', 1),
    'feeding_tube': ('Feeding tube', 1),
    'skin_burn': ('Severe skin burn or condition', 1),
    'intractable_epilepsy': ('Intractable epilepsy', 1),
    'malnutrition': ('Malnutrition or at risk', 1),
    'immunity_disorders': ('Disorders of immunity, except RxImmune', 1),
    'cirrhosis': ('Cirrhosis of liver', 1),
    'ostomy': ('Ostomy', 1),
    'respiratory_arrest': ('Respiratory arrest', 1),
    'pulmonary_fibrosis': ('Pulmonary fibrosis and other chronic lung disorders', 1),
}
# NTA points -> band letter, highest first.
NTA_BANDS = ((12, 'A'), (9, 'B'), (6, 'C'), (3, 'D'), (1, 'E'), (0, 'F'))
HIPPS = re.compile(r'^[A-P][A-L][A-Y][A-F][0-9A-Z]$')


def _choices(labels):
    return [dict(value=label, label=label) for label in labels]


# Cell id -> how it is shown and what it accepts. Order is the page's order.
FIELDS = {
    'pt_ot.primary_diagnosis': dict(group='PT/OT', label='Primary diagnosis', kind='choice',
        options=_choices(PT_OT_CATEGORIES)),
    'pt_ot.gg': dict(group='PT/OT', label='GG', kind='score', min=0, max=24),
    'slp.cognitive_impairment': dict(group='SLP', label='Cognitive Ability', kind='choice', options=YES_NO),
    'slp.acute_neuro': dict(group='SLP', label='Acute Neuro Primary', kind='choice', options=YES_NO),
    'slp.comorbidity': dict(group='SLP', label='Comorbidity', kind='choice', options=YES_NO),
    'slp.mechanically_altered_diet': dict(group='SLP', label='MAD', kind='choice', options=YES_NO),
    'slp.swallowing_disorder': dict(group='SLP', label='SD', kind='choice', options=YES_NO),
    'nursing.category': dict(group='Nursing', label='Clinical category', kind='choice',
        options=_choices(NURSING_CATEGORIES)),
    'nursing.gg': dict(group='Nursing', label='GG', kind='score', min=0, max=16),
    'nursing.depression': dict(group='Nursing', label='Depression', kind='choice', options=YES_NO),
    'nta': dict(group='NTA', label='Diagnoses', kind='diagnoses',
        options=[dict(value=key, label=label, points=points) for key, (label, points) in NTA_CONDITIONS.items()]),
    'projected_hipps': dict(group='Projected HIPPS', label='Projected HIPPS', kind='hipps'),
    # Final HIPPS is not entered: it is the coded assessment's own (final_hipps on the row).
}
# One more part in every group: Notes, free text. Its text is the entry's note;
# the latest shows in the cell and the log keeps the rest. The cell ids stay
# *.reply -- the part was first called Reply -- so entries already saved under
# them still show.
FIELDS = {**FIELDS, **{f'{prefix}.reply': dict(group=group, label='Notes', kind='text') for prefix, group in (
    ('pt_ot', 'PT/OT'), ('slp', 'SLP'), ('nursing', 'Nursing'), ('nta', 'NTA'),
    ('projected_hipps', 'Projected HIPPS'))}}
# The page's order: each group's parts, then its Notes.
FIELDS = dict(sorted(FIELDS.items(), key=lambda item: [spec['group'] for spec in FIELDS.values()].index(item[1]['group'])))

SORTS = {'resident': 'resident_name', 'facility': 'facility_name', 'payer': 'payer_label',
    'medicare-start': 'medicare_start', 'active': 'active', 'ard': 'ard', 'mds-due': 'due_sort'}
FILTERS = {'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer': 'payer_label', 'active': 'active', 'mds-due': 'mds_status'}
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_label')


class WorksheetQuery(PageQuery):
    # Inclusive range of dates, applied to each stay's start (start) or its
    # 5-day assessment's ARD (ard).
    start_date: date
    end_date: date
    date_basis: Literal['start', 'ard'] = 'start'
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('end_date')
    @classmethod
    def valid_range(cls, value, info):
        start = info.data.get('start_date')
        if start is not None and start > value:
            raise ValueError('start_date must be on or before end_date.')
        if start is not None and (value - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f'The range is at most {MAX_RANGE_DAYS} days.')
        return value

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        try:
            filters = json.loads(value)
        except ValueError:
            raise ValueError('filters must be a JSON object of selected values.') from None
        if not isinstance(filters, dict) or any(key not in FILTERS for key in filters):
            raise ValueError('Unsupported worksheet filter.')
        if any(not isinstance(values, list) or any(not isinstance(item, str) for item in values)
                for values in filters.values()):
            raise ValueError('Each filter must be a list of strings.')
        return value


class WorksheetFilterQuery(WorksheetQuery):
    column: str = Field(max_length=100)


class Cell(BaseModel):
    value: str | None
    label: str | None
    note: str | None
    author: str
    created_at: datetime
    entry_id: UUID


class NtaItem(BaseModel):
    value: str
    label: str
    points: int
    note: str | None
    author: str
    entry_id: UUID


class Nta(BaseModel):
    items: list[NtaItem]
    points: int
    band: str


class WorksheetRow(BaseModel):
    payer_stay_id: UUID
    stay_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_label: str
    medicare_start: date = Field(description='First day of this Medicare payer period.')
    active: str = Field(description='Yes if this Medicare stay is still running on the latest census day.')
    start_reason: str = Field(description='How the Medicare stay began: Admission, or Disenrollment -- a move '
        'from Medicare Advantage into Original Medicare mid-stay.')
    end_reason: str | None = Field(description='Why an ended stay ended: Payer change or Discharge; null while active.')
    ended_on: date | None = Field(description='The ended stay\'s last day; null while active.')
    ard: date | None = Field(description="The 5-day assessment's reference date.")
    due_date: date | None = Field(description='ARD plus 14 days; null once the MDS is complete.')
    mds_status: str = Field(description='Complete, Due or Overdue.')
    final_rates: 'StayRates | None' = Field(description='Final HIPPS priced over a 100-day stay.')
    projected_rates: 'StayRates | None' = Field(description='Projected HIPPS, once entered, priced over a 100-day stay.')
    final_hipps: str | None = Field(description='The coded PDPM code plus the 5-day assessment indicator, 1; '
        'null until the MDS is coded.')
    cells: dict[str, Cell] = Field(description='Latest set entry per cell, by cell id.')
    nta: Nta
    # Entries per cell, replies included, so the page can show where there is talk.
    activity: dict[str, int]


class StayRates(BaseModel):
    average_rate: float = Field(description='Total revenue over the days, per day.')
    neutral_rate: float = Field(description='The case-mix-neutral average: $720 national, every CMI 1.0.')
    total_revenue: float = Field(description='Every day of a full 100-day Medicare stay at this code.')


WorksheetRow.model_rebuild()


class WorksheetPage(Page[WorksheetRow]):
    census_date: date


class Entry(BaseModel):
    entry_id: UUID
    field: str
    action: str
    value: str | None
    label: str | None
    note: str | None
    reply_to: UUID | None
    author: str
    created_at: datetime


class NewEntry(BaseModel):
    field: str = Field(max_length=40)
    action: str = Field(pattern='^(set|add|remove|reply)$')
    value: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=4000)
    reply_to: UUID | None = None


def catalog():
    return dict(fields=[dict(id=field, **spec) for field, spec in FIELDS.items()], mds_due_days=MDS_DUE_DAYS)


def _label(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    if field == 'nta':
        return NTA_CONDITIONS[value][0] if value in NTA_CONDITIONS else value
    return value


def _rows(query: WorksheetQuery, census_date: date, exclude=None):
    """Medicare PDPM stays whose start -- or ARD, by date_basis -- falls in the
    range. Status is judged on the
    latest census day: coded by then is Complete, past due by then Overdue."""
    day = literal(census_date, Date)
    complete = func.coalesce(assessments.c.coded_date <= day, False)
    due = assessments.c.ard + MDS_DUE_DAYS
    rows = select(
        periods.c.payer_stay_id, periods.c.stay_id,
        (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio, regions.c.region,
        case({payer_type: GROUP_LABELS[group] for payer_type, group in MEDICARE.items()},
            value=payers.c.payer_type, else_=payers.c.payer_type).label('payer_label'),
        periods.c.start_date.label('medicare_start'),
        # This Medicare stay still running on the census day. Not the same as in
        # the building: a resident who moved to another payer is still there.
        # end_date is the day after the last day, as census_logs ranges are.
        case((or_(periods.c.end_date.is_(None), periods.c.end_date > day), 'Yes'),
            else_='No').label('active'),
        # A Medicare stay that began on a payer change, not at admission, is a
        # disenrollment: every one moves a resident from Medicare Advantage into
        # Original Medicare (MANAGED_MEDICARE in the ADT simulation).
        case((periods.c.start_reason == 'payer_change', 'Disenrollment'), else_='Admission').label('start_reason'),
        # Why it ended, once it has by the census day. end_date is exclusive.
        case((periods.c.end_date <= day, case((periods.c.end_reason == 'discharge', 'Discharge'),
            else_='Payer change')), else_=None).label('end_reason'),
        case((periods.c.end_date <= day, periods.c.end_date - 1), else_=None).label('ended_on'),
        assessments.c.ard,
        case((complete, None), else_=due).label('due_date'),
        case((complete, 'Complete'), (due < day, 'Overdue'), else_='Due').label('mds_status'),
        # Filled from the assessment once coded, never entered: its PDPM code and
        # the assessment indicator, 1 for the 5-day assessment.
        case((complete, assessments.c.pdpm_code + FIVE_DAY_INDICATOR), else_=None).label('final_hipps'),
        # The stay's contract rate: what a code's case-mix factor multiplies.
        contracts.c.daily_rate.label('contract_rate'),
        # Complete sorts after every date, as the column reads.
        case((complete, None), else_=due).label('due_sort'),
    )
    by_ard = query.date_basis == 'ard'
    # Start from whichever date the range applies to, so its index narrows the
    # rows first. With this many tables PostgreSQL largely keeps the written
    # join order, and starting from periods it joined all 80k Medicare periods
    # before filtering by ARD: 540 ms against about 100 ms by stay start.
    source = (assessments.join(periods, periods.c.payer_stay_id == assessments.c.payer_stay_id)
        if by_ard else periods)
    source = (source
        .join(payers, payers.c.payer_id == periods.c.payer_id)
        .join(stays, stays.c.stay_id == periods.c.stay_id)
        # A PDPM contract, as Current Medicare PDPM counts: per diem plans are out.
        .join(contracts, (contracts.c.facility_id == stays.c.facility_id)
            & (contracts.c.payer_id == periods.c.payer_id) & (contracts.c.payment_method == 'pdpm'))
        .join(residents, residents.c.resident_id == stays.c.resident_id)
        .join(facilities, facilities.c.facility_id == stays.c.facility_id)
        .join(regions).join(portfolios))
    if not by_ard:
        # By stay start, a stay is listed even before it has an assessment.
        source = source.outerjoin(assessments, assessments.c.payer_stay_id == periods.c.payer_stay_id)
    rows = rows.select_from(source).where(payers.c.payer_type.in_(MEDICARE),
        # The range applies to the stay's start or its ARD, as the page's toggle says.
        (assessments.c.ard if by_ard else periods.c.start_date).between(query.start_date, query.end_date))
    listed = rows.cte('listed').prefix_with('MATERIALIZED')
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result, listed


def _cells(connection: Connection, payer_stay_ids: list[UUID]):
    """Each period's cells, NTA list and activity, built from its log in order."""
    built = {key: dict(cells={}, nta={}, activity={}) for key in payer_stay_ids}
    if not payer_stay_ids:
        return built
    for entry in connection.execute(select(entries).where(entries.c.payer_stay_id.in_(payer_stay_ids))
            .order_by(entries.c.created_at, entries.c.entry_id)).mappings():
        sheet = built[entry['payer_stay_id']]
        field = entry['field']
        sheet['activity'][field] = sheet['activity'].get(field, 0) + 1
        if entry['action'] == 'set':
            sheet['cells'][field] = dict(value=entry['value'], label=_label(field, entry['value']),
                note=entry['note'], author=entry['author'], created_at=entry['created_at'],
                entry_id=entry['entry_id'])
        elif entry['action'] == 'add':
            label, points = NTA_CONDITIONS.get(entry['value'], (entry['value'], 0))
            sheet['nta'][entry['value']] = dict(value=entry['value'], label=label, points=points,
                note=entry['note'], author=entry['author'], entry_id=entry['entry_id'])
        elif entry['action'] == 'remove':
            sheet['nta'].pop(entry['value'], None)
    for sheet in built.values():
        items = list(sheet['nta'].values())
        points = sum(item['points'] for item in items)
        sheet['nta'] = dict(items=items, points=points,
            band=next(letter for floor, letter in NTA_BANDS if points >= floor))
    return built


def page(connection: Connection, query: WorksheetQuery, today: date):
    if query.sort is not None and query.sort not in SORTS:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, today)
    result, listed = _rows(query, census_date)
    column = listed.c[SORTS[query.sort or 'resident']]
    order = (column.desc() if query.direction == 'desc' else column.asc()).nulls_last()
    rows = connection.execute(result.add_columns(func.count().over().label('total'))
        .order_by(order, listed.c.payer_stay_id).limit(query.limit).offset(query.offset)).mappings().all()
    total = rows[0]['total'] if rows else connection.scalar(select(func.count()).select_from(result.subquery()))
    sheets = _cells(connection, [row['payer_stay_id'] for row in rows])
    def priced(code):
        # Over a full 100-day Medicare stay, at the stay's own contract rate,
        # by the same formula the generator prices every PDPM day with.
        return lambda row: pdpm_rates.stay(code(row), row['contract_rate']) if code(row) else None
    final = priced(lambda row: row['final_hipps'])
    projected = priced(lambda row: (sheets[row['payer_stay_id']]['cells'].get('projected_hipps') or {}).get('value'))
    return dict(items=[dict(row, **sheets[row['payer_stay_id']], final_rates=final(row), projected_rates=projected(row))
            for row in rows], total=total,
        limit=query.limit, offset=query.offset, census_date=census_date)


def options(connection: Connection, query: WorksheetFilterQuery, today: date):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    result, listed = _rows(query, census_day(connection, today), exclude=query.column)
    column = listed.c[FILTERS[query.column]]
    return dict(options=sorted(connection.scalars(
        result.with_only_columns(cast(column, String).label('option')).distinct())))


def log(connection: Connection, payer_stay_id: UUID, field: str):
    """Every entry and reply on one cell, oldest first."""
    if field not in FIELDS:
        raise ApiError('invalid_field', 'Unknown worksheet cell.')
    return [dict(entry, label=_label(field, entry['value'])) for entry in connection.execute(
        select(entries).where(entries.c.payer_stay_id == payer_stay_id, entries.c.field == field)
        .order_by(entries.c.created_at, entries.c.entry_id)).mappings()]


def _check_value(field: str, value: str | None):
    spec = FIELDS[field]
    if value is None or not value.strip():
        raise ApiError('invalid_value', f'{spec["label"]} needs a value.')
    if spec['kind'] == 'choice' and value not in {option['value'] for option in spec['options']}:
        raise ApiError('invalid_value', f'{value} is not an option for {spec["label"]}.')
    if spec['kind'] == 'score' and not (value.isdigit() and spec['min'] <= int(value) <= spec['max']):
        raise ApiError('invalid_value', f'{spec["label"]} is a whole number from {spec["min"]} to {spec["max"]}.')
    if spec['kind'] == 'hipps' and not HIPPS.match(value):
        raise ApiError('invalid_value', 'A HIPPS code is five characters: PT/OT A-P, SLP A-L, nursing A-Y, '
            'NTA A-F, then the assessment indicator.')
    if spec['kind'] == 'diagnoses' and value not in NTA_CONDITIONS:
        raise ApiError('invalid_value', 'Unknown NTA diagnosis.')


def add_entry(connection: Connection, payer_stay_id: UUID, new: NewEntry, author: str):
    """Validate and append one entry. The write connection commits on return."""
    if new.field not in FIELDS:
        raise ApiError('invalid_field', 'Unknown worksheet cell.')
    if connection.scalar(select(assessments.c.payer_stay_id)
            .where(assessments.c.payer_stay_id == payer_stay_id)) is None:
        raise ApiError('not_found', 'No PDPM assessment for that Medicare stay.', 404)
    kind = FIELDS[new.field]['kind']
    note = new.note.strip() if new.note and new.note.strip() else None
    value = new.value.strip().upper() if kind == 'hipps' and new.value else new.value
    if new.action == 'reply':
        if note is None or new.reply_to is None:
            raise ApiError('invalid_reply', 'A reply needs the entry it answers and some text.')
        if connection.scalar(select(entries.c.entry_id).where(entries.c.entry_id == new.reply_to,
                entries.c.payer_stay_id == payer_stay_id, entries.c.field == new.field)) is None:
            raise ApiError('invalid_reply', 'That entry is not on this cell.')
        value = None
    elif kind == 'diagnoses':
        if new.action not in ('add', 'remove'):
            raise ApiError('invalid_action', 'NTA diagnoses are added or removed.')
        _check_value(new.field, value)
    elif kind == 'text':
        # Notes is its text alone, kept as the note.
        if new.action != 'set' or note is None:
            raise ApiError('invalid_value', 'Notes needs some text.')
        value = None
    else:
        if new.action != 'set':
            raise ApiError('invalid_action', 'This cell is set, not added to.')
        _check_value(new.field, value)
    row = dict(entry_id=uuid4(), payer_stay_id=payer_stay_id, field=new.field, action=new.action,
        value=value, note=note, reply_to=new.reply_to if new.action == 'reply' else None, author=author)
    # The wall clock, not now(): now() is the transaction's start, so entries in
    # one transaction would tie and replay out of order.
    created = connection.execute(insert(entries).values(**row, created_at=func.clock_timestamp())
        .returning(entries.c.created_at)).scalar_one()
    return dict(row, created_at=created, label=_label(new.field, value))
