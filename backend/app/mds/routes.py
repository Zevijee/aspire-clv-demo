from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ..common.dates import today
from ..common.errors import ApiError, ErrorResponse
from ..auth.routes import require_user
from ..database import DbConnection, DbWriteConnection
from .schemas import CurrentMedicare
from .service import current
from . import categories, residents, worksheet

router = APIRouter(prefix='/mds', tags=['MDS'])


@router.get('/current-medicare', response_model=CurrentMedicare, responses={409: {'model': ErrorResponse}})
def current_medicare(request: Request, connection: DbConnection):
    """Every facility's PDPM residents on the latest census day, split into
    Federal Medicare and Managed Medicare PDPM, with summed actual and
    case-mix-neutral daily rates and days since admission for the page to
    average at any scope. Managed Medicare PPO, a per diem payer, is left out."""
    return current(connection, today(request.app.state.settings.timezone))


@router.get('/current-medicare/categories', response_model=categories.Categories,
    responses={409: {'model': ErrorResponse}})
def current_medicare_categories(request: Request, connection: DbConnection):
    """Every facility's PDPM residents on the latest census day, counted by PDPM
    category. Primary diagnosis is the PT/OT clinical category of the code."""
    return categories.categories(connection, today(request.app.state.settings.timezone))


@router.get('/current-medicare/residents', response_model=residents.ResidentsPage,
    responses={409: {'model': ErrorResponse}})
def current_medicare_residents(request: Request, connection: DbConnection,
        query: Annotated[residents.ResidentsQuery, Query()]):
    """Every PDPM resident on the latest census day, with payer group, plan,
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


@router.get('/pdpm-worksheet/catalog')
def pdpm_worksheet_catalog():
    """The worksheet's cells: what each is called, what it accepts, the NTA list."""
    return worksheet.catalog()


@router.get('/pdpm-worksheet', response_model=worksheet.WorksheetPage, responses={409: {'model': ErrorResponse}})
def pdpm_worksheet(request: Request, connection: DbConnection,
        query: Annotated[worksheet.WorksheetQuery, Query()]):
    """Today's PDPM residents with their ARD, MDS due date and worksheet cells."""
    return worksheet.page(connection, query, today(request.app.state.settings.timezone))


@router.get('/pdpm-worksheet/filter-options')
def pdpm_worksheet_options(request: Request, connection: DbConnection,
        query: Annotated[worksheet.WorksheetFilterQuery, Query()]):
    return worksheet.options(connection, query, today(request.app.state.settings.timezone))


@router.get('/pdpm-worksheet/{payer_stay_id}/entries', response_model=list[worksheet.Entry])
def pdpm_worksheet_log(connection: DbConnection, payer_stay_id: UUID, field: str = Query(max_length=40)):
    """Every entry and reply on one cell, oldest first."""
    return worksheet.log(connection, payer_stay_id, field)


@router.post('/pdpm-worksheet/{payer_stay_id}/entries', response_model=worksheet.Entry,
    responses={400: {'model': ErrorResponse}, 404: {'model': ErrorResponse}})
def pdpm_worksheet_add(connection: DbWriteConnection, payer_stay_id: UUID, entry: worksheet.NewEntry,
        user: Annotated[str, Depends(require_user)]):
    """Append one entry to a cell's log. The only report route that writes:
    worksheet entries are what people enter, kept as an append-only log."""
    return worksheet.add_entry(connection, payer_stay_id, entry, user)
