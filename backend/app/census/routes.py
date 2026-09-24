from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..common.dates import today
from ..common.errors import ApiError, ErrorResponse
from ..database import DbConnection
from .schemas import LiveCensus
from .service import live
from . import residents

router = APIRouter(prefix='/census', tags=['Census'])


@router.get('/live', response_model=LiveCensus, responses={409: {'model': ErrorResponse}})
def live_census(request: Request, connection: DbConnection):
    """Every facility's current census and skilled census, against the previous
    calendar month's average daily census.

    Takes no dates: the period is the report's own. Census is read from the latest
    completed day on or before the report's today. Previous-month averages are
    null when that month is not completely generated, rather than an average over
    the days that happen to exist.
    """
    return live(connection, today(request.app.state.settings.timezone))


@router.get('/residents', response_model=residents.ResidentsPage, responses={409: {'model': ErrorResponse}})
def census_residents(request: Request, connection: DbConnection,
        query: Annotated[residents.ResidentsQuery, Query()]):
    """Every resident in a bed at the close of the census day, one row per stay.

    The day is `end_date` when given, otherwise the latest completed day on or
    before the report's today. The count equals that day's census.
    """
    return residents.page(connection, query, today(request.app.state.settings.timezone))


@router.get('/residents/filter-options')
def census_resident_options(request: Request, connection: DbConnection,
        query: Annotated[residents.FilterQuery, Query()]):
    return residents.options(connection, query, today(request.app.state.settings.timezone))


@router.get('/residents/export')
def census_resident_export(request: Request, query: Annotated[residents.ResidentsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if not residents.valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    report_today = today(request.app.state.settings.timezone)
    return StreamingResponse(residents.csv_chunks(request.app.state.database, query, report_today),
        media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="census-residents.csv"'})
