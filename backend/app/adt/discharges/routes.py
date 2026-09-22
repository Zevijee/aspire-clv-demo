from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...common.errors import ErrorResponse
from ...common.tables import Page
from ...database import DbConnection
from .schemas import Overview, OverviewQuery
from .service import overview
from . import logs

router = APIRouter(prefix='/adt/discharges', tags=['Discharges'])


@router.get('/overview', response_model=Overview, responses={409: {'model': ErrorResponse}})
def discharges_overview(connection: DbConnection, query: Annotated[OverviewQuery, Query()]):
    """One period from saved daily discharge facts. Request the prior period separately.

    Payer, destination and disposition breakdowns each exclude their own filter
    while keeping the other two; totals, location rows and daily counts apply all
    three. Length of stay is returned as a sum beside its count, with the average
    derived from that pair rather than from per-row averages.
    """
    return overview(connection, query)


@router.get('/logs', response_model=Page[logs.Discharge])
def discharge_logs(connection: DbConnection, query: Annotated[logs.LogsQuery, Query()]):
    return logs.page(connection, query)


@router.get('/logs/filter-options')
def discharge_log_options(connection: DbConnection, query: Annotated[logs.FilterQuery, Query()]):
    return logs.options(connection, query)


@router.get('/logs/export')
def discharge_log_export(request: Request, query: Annotated[logs.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in logs.columns:
        from ...common.errors import ApiError
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(logs.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="discharges-{query.start_date}-to-{query.end_date}.csv"'})
