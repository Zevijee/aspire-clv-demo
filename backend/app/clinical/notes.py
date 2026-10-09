"""Flagged Progress Notes: every note from the last 10 days with a watch word in
it, newest first, with its full text for the page to open.

Read from progress_notes, which keeps only those 10 days; the seeder found each
note's flag_terms in its text. A note with none is not listed. Sorting,
filtering, the column menus and the CSV share one statement, as the incident and
transfer logs do. The Flag terms filter keeps a note with any selected term.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.dialects import postgresql

from shared.database.schema import facilities, payers, portfolios, progress_notes as notes, regions, residents
from ..adt.discharges.logs import PAYER_LABELS
from ..common.dates import OptionalDate
from ..common.errors import ApiError
from ..common.tables import PageQuery, paginate

resident_name = residents.c.first_name + ' ' + residents.c.last_name
payer_label = case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type)
# Each column id -> what it sorts, filters and searches on.
COLUMNS = {
    'note-date': notes.c.note_date, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region, 'resident': resident_name,
    'note-type': notes.c.note_type, 'payer': payer_label, 'clinician': notes.c.clinician,
    'flag-terms': func.array_to_string(notes.c.flag_terms, ', '),
}
FILTERS = ('facility', 'state', 'portfolio', 'region', 'note-type', 'payer', 'clinician', 'flag-terms')


class NotesQuery(PageQuery):
    # The shared filter-options client always sends a range; the notes are the
    # last 10 days whatever it says, so both are accepted and ignored.
    start_date: OptionalDate = None
    end_date: OptionalDate = None
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        try:
            filters = json.loads(value)
        except ValueError:
            raise ValueError('filters must be a JSON object of selected values.') from None
        if not isinstance(filters, dict) or any(key not in FILTERS for key in filters):
            raise ValueError('Unsupported note filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(NotesQuery):
    column: str = Field(max_length=100)


class FlaggedNote(BaseModel):
    note_id: UUID
    note_date: date
    facility_name: str
    state: str
    portfolio: str
    region: str
    resident_name: str
    note_type: str
    payer_type: str
    clinician: str
    flag_terms: list[str] = Field(description='The watch words in the text, alphabetically.')
    note_text: str


def statement(query: NotesQuery, exclude=None):
    result = select(notes.c.note_id, notes.c.note_date, facilities.c.facility.label('facility_name'),
        portfolios.c.state, portfolios.c.portfolio, regions.c.region, resident_name.label('resident_name'),
        notes.c.note_type, payer_label.label('payer_type'), notes.c.clinician, notes.c.flag_terms,
        notes.c.note_text,
    ).select_from(notes.join(residents, residents.c.resident_id == notes.c.resident_id)
        .join(facilities, notes.c.facility_id == facilities.c.facility_id)
        .join(regions).join(portfolios).join(payers, notes.c.payer_id == payers.c.payer_id)
    ).where(func.cardinality(notes.c.flag_terms) > 0)
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == 'flag-terms':
            # Any of the chosen terms.
            result = result.where(notes.c.flag_terms.op('&&')(cast(values, postgresql.ARRAY(String))))
        else:
            result = result.where(cast(COLUMNS[key], String).in_(values))
    if query.search.strip():
        text = query.search.strip()
        result = result.where(or_(*(cast(column, String).icontains(text, autoescape=True)
            for column in (*COLUMNS.values(), notes.c.note_text))))
    return result


def _ordered(query: NotesQuery):
    return paginate(statement(query), query, columns=COLUMNS, default_sort='note-date', unique_key=notes.c.note_id)


def page(connection, query: NotesQuery):
    total = connection.scalar(select(func.count()).select_from(statement(query).subquery()))
    return dict(items=connection.execute(_ordered(query)).mappings().all(), total=total,
        limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    source = statement(query, exclude=query.column).subquery()
    if query.column == 'flag-terms':
        # One option per term, not per combination.
        terms = select(func.unnest(source.c.flag_terms).label('term')).subquery()
        return dict(options=list(connection.scalars(select(terms.c.term).distinct().order_by(terms.c.term))))
    column = {'facility': 'facility_name', 'payer': 'payer_type', 'note-type': 'note_type'}.get(
        query.column, query.column)
    return dict(options=list(connection.scalars(select(cast(source.c[column], String).label('option'))
        .distinct().order_by('option'))))


EXPORT_COLUMNS = (
    ('Date', 'note_date'), ('Facility', 'facility_name'), ('State', 'state'), ('Portfolio', 'portfolio'),
    ('Region', 'region'), ('Resident', 'resident_name'), ('Note type', 'note_type'), ('Payer', 'payer_type'),
    ('Clinician', 'clinician'), ('Flag terms', 'flag_terms'), ('Note', 'note_text'),
)


def csv_chunks(database, query: NotesQuery):
    with database.connection() as connection:
        source = _ordered(query).limit(None).offset(None)
        with connection.execute(source.execution_options(yield_per=1000)) as result:
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow([label for label, _ in EXPORT_COLUMNS])
            yield '﻿' + buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            for row in result.mappings():
                values = []
                for _, key in EXPORT_COLUMNS:
                    value = row[key]
                    if isinstance(value, list):
                        value = ', '.join(value)
                    if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
                if buffer.tell() > 65536:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate(0)
            if buffer.tell():
                yield buffer.getvalue()
