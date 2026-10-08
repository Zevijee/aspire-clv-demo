"""Medicaid PDPM Worksheet: the Medicare PDPM Worksheet for Texas Medicaid. One
row per Texas Medicaid payer period whose start -- or first assessment's ARD --
falls in the chosen range, with the cells Texas's case mix needs: the nursing
component, the NTA comorbidities and a projected two-letter code, nursing
letter then NTA letter. The final code is not entered: it is the first
assessment's own, once coded.

Texas only, as the other Medicaid reports: its Medicaid pays on the PDPM
nursing and NTA components; Florida and Pennsylvania use other systems.

Entries go to the same append-only pdpm_worksheet_entries log as Medicare's,
one worksheet per payer period, so a Medicaid period's cells never mix with a
Medicare one's. Reading and writing the log is worksheet.py's, given this
worksheet's catalogue. No code is priced: a Texas Medicaid rate here is the
census day's rate, not a function of the code.
"""
import json
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, and_, case, cast, func, literal, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    facilities, medicaid_assessments as assessments, payers, portfolios, regions, res_payer_stays as periods,
    res_stays as stays, residents)
from ..common.errors import ApiError
from ..common.tables import Page
from . import worksheet
from .medicaid import STATES
from .service import census_day
from .worksheet import FIELDS as MEDICARE_FIELDS, MDS_DUE_DAYS, Cell, Nta

# The Medicare worksheet's nursing and NTA cells, as they are: Texas codes the
# same components. Then a projected code in place of the projected HIPPS.
FIELDS = {field: spec for field, spec in MEDICARE_FIELDS.items() if spec['group'] in ('Nursing', 'NTA')}
FIELDS |= {
    'projected_code': dict(group='Projected code', label='Projected code', kind='code', length=2,
        example='e.g. KC', pattern=r'^[A-Y][A-F]$',
        hint='A Texas Medicaid code is two letters: nursing A-Y, then NTA A-F.'),
    'projected_code.reply': dict(group='Projected code', label='Notes', kind='text'),
}

SORTS = {'resident': 'resident_name', 'facility': 'facility_name', 'payer-name': 'payer_name',
    'medicaid-start': 'medicaid_start', 'active': 'active', 'ard': 'ard', 'mds-due': 'due_sort'}
FILTERS = {'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer-name': 'payer_name', 'active': 'active', 'mds-due': 'mds_status'}
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_name')


class WorksheetQuery(worksheet.WorksheetQuery):
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


class WorksheetRow(BaseModel):
    payer_stay_id: UUID
    stay_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_name: str
    medicaid_start: date = Field(description='First day of this Medicaid payer period.')
    active: str = Field(description='Yes if this Medicaid stay is still running on the latest census day.')
    start_reason: str = Field(description='How the Medicaid stay began: Admission, or Payer change.')
    end_reason: str | None = Field(description='Why an ended stay ended: Payer change or Discharge; null while active.')
    ended_on: date | None = Field(description="The ended stay's last day; null while active.")
    ard: date | None = Field(description="The first assessment's reference date.")
    due_date: date | None = Field(description='ARD plus 14 days; null once the MDS is complete.')
    mds_status: str = Field(description='Complete, Due or Overdue.')
    final_code: str | None = Field(description="The first assessment's two-letter code; null until coded.")
    cells: dict[str, Cell]
    nta: Nta
    activity: dict[str, int]


class WorksheetPage(Page[WorksheetRow]):
    census_date: date


def catalog():
    return dict(fields=[dict(id=field, **spec) for field, spec in FIELDS.items()], mds_due_days=MDS_DUE_DAYS)


def _rows(query: WorksheetQuery, census_date: date, exclude=None):
    """Texas Medicaid stays whose start -- or first ARD -- falls in the range,
    judged on the latest census day as the Medicare worksheet judges its own."""
    day = literal(census_date, Date)
    by_ard = query.date_basis == 'ard'
    # The range's Medicaid periods first, from the date column alone, as
    # Historical Medicaid selects them: joined to Texas first, PostgreSQL takes
    # Texas for one row and walks every Texas stay.
    basis = (select(assessments.c.payer_stay_id).where(assessments.c.segment == 1,
            assessments.c.ard.between(query.start_date, query.end_date)) if by_ard
        else select(periods.c.payer_stay_id).where(periods.c.start_date.between(query.start_date, query.end_date)))
    candidates = (select(periods.c.payer_stay_id, periods.c.stay_id, periods.c.start_date, periods.c.end_date,
            periods.c.start_reason, periods.c.end_reason, payers.c.payer_name, stays.c.facility_id,
            stays.c.resident_id)
        .select_from(periods.join(payers, payers.c.payer_id == periods.c.payer_id)
            .join(stays, stays.c.stay_id == periods.c.stay_id))
        .where(periods.c.payer_stay_id.in_(basis), payers.c.payer_type == 'medicaid', periods.c.start_date <= day)
        .cte('candidates').prefix_with('MATERIALIZED'))
    first = assessments.alias('first_assessment')
    complete = func.coalesce(first.c.coded_date <= day, False)
    due = first.c.ard + MDS_DUE_DAYS
    rows = (select(
            candidates.c.payer_stay_id, candidates.c.stay_id,
            (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
            facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio, regions.c.region,
            candidates.c.payer_name, candidates.c.start_date.label('medicaid_start'),
            # end_date is the day after the last day, as census_logs ranges are.
            case((or_(candidates.c.end_date.is_(None), candidates.c.end_date > day), 'Yes'), else_='No').label('active'),
            case((candidates.c.start_reason == 'payer_change', 'Payer change'), else_='Admission').label('start_reason'),
            case((candidates.c.end_date <= day, case((candidates.c.end_reason == 'discharge', 'Discharge'),
                else_='Payer change')), else_=None).label('end_reason'),
            case((candidates.c.end_date <= day, candidates.c.end_date - 1), else_=None).label('ended_on'),
            first.c.ard,
            case((complete, None), else_=due).label('due_date'),
            case((complete, 'Complete'), (due < day, 'Overdue'), else_='Due').label('mds_status'),
            case((complete, first.c.code), else_=None).label('final_code'),
            # Complete sorts after every date, as the column reads.
            case((complete, None), else_=due).label('due_sort'))
        .select_from(candidates
            .join(facilities, facilities.c.facility_id == candidates.c.facility_id).join(regions).join(portfolios)
            .join(residents, residents.c.resident_id == candidates.c.resident_id)
            # By stay start, a stay is listed even before it has an assessment.
            .outerjoin(first, and_(first.c.payer_stay_id == candidates.c.payer_stay_id, first.c.segment == 1)))
        .where(portfolios.c.state.in_(STATES)))
    listed = rows.cte('listed').prefix_with('MATERIALIZED')
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result, listed


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
    sheets = worksheet._cells(connection, [row['payer_stay_id'] for row in rows])
    return dict(items=[dict(row, **sheets[row['payer_stay_id']]) for row in rows], total=total,
        limit=query.limit, offset=query.offset, census_date=census_date)


def options(connection: Connection, query: WorksheetFilterQuery, today: date):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    result, listed = _rows(query, census_day(connection, today), exclude=query.column)
    column = listed.c[FILTERS[query.column]]
    return dict(options=sorted(connection.scalars(
        result.with_only_columns(cast(column, String).label('option')).distinct())))


def _texas_medicaid(payer_stay_id: UUID):
    """The payer period, only if it is a Texas Medicaid one: the stays this worksheet lists."""
    return (select(periods.c.payer_stay_id)
        .select_from(periods.join(payers, payers.c.payer_id == periods.c.payer_id)
            .join(stays, stays.c.stay_id == periods.c.stay_id)
            .join(facilities, facilities.c.facility_id == stays.c.facility_id).join(regions).join(portfolios))
        .where(periods.c.payer_stay_id == payer_stay_id, payers.c.payer_type == 'medicaid',
            portfolios.c.state.in_(STATES)))


def log(connection: Connection, payer_stay_id: UUID, field: str):
    return worksheet.log(connection, payer_stay_id, field, FIELDS)


def add_entry(connection: Connection, payer_stay_id: UUID, new: worksheet.NewEntry, author: str):
    return worksheet.add_entry(connection, payer_stay_id, new, author, FIELDS, _texas_medicaid)
