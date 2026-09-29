from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..common.dates import today
from ..common.errors import ApiError, ErrorResponse
from ..database import DbConnection
from .schemas import CurrentMedicare
from .service import current
from . import residents

router = APIRouter(prefix='/mds', tags=['MDS'])


@router.get('/current-medicare', response_model=CurrentMedicare, responses={409: {'model': ErrorResponse}})
def current_medicare(request: Request, connection: DbConnection):
    """Every facility's Medicare residents on the latest census day, split into
    Federal, HMO and commercial plans, with summed actual and case-mix-neutral daily
    rates and days since admission for the page to average at any scope."""
    return current(connection, today(request.app.state.settings.timezone))


@router.get('/current-medicare/residents', response_model=residents.ResidentsPage,
    responses={409: {'model': ErrorResponse}})
def current_medicare_residents(request: Request, connection: DbConnection,
        query: Annotated[residents.ResidentsQuery, Query()]):
    """Every resident on a Medicare payer on the latest census day, with payer,
    length of stay, PDPM score, average rate and revenue to date."""
    return residents.page(connection, query, today(request.app.state.settings.timezone))


@router.get('/current-medicare/residents/filter-options')
def current_medicare_resident_options(request: Request, connection: DbConnection,
        query: Annotated[residents.FilterQuery, Query()]):
    return residents.options(connection, query, today(request.app.state.settings.timezone))


@router.get('/current-medicare/residents/export')
def current_medicare_resident_export(request: Request,
        query: Annotated[residents.ResidentsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if not residents.valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(residents.csv_chunks(request.app.state.database, query,
        today(request.app.state.settings.timezone)), media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="current-medicare-residents.csv"'})
