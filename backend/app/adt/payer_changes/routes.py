from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...common.errors import ErrorResponse
from ...common.tables import Page
from ...database import DbConnection
from .schemas import Overview, OverviewQuery
from .service import overview
from . import logs

router = APIRouter(prefix='/adt/payer-changes', tags=['Payer changes'])


@router.get('/overview', response_model=Overview, responses={409: {'model': ErrorResponse}})
def payer_changes_overview(connection: DbConnection, query: Annotated[OverviewQuery, Query()]):
    """One period from saved daily payer change facts. Request the prior period separately.

    Counts are read from the fact table at payer-type grain. Residents affected
    is a distinct count taken from the source periods, so it is exact but is not
    additive across scopes: a resident who changed payer in two facilities is
    counted in both.
    """
    return overview(connection, query)


@router.get('/logs', response_model=Page[logs.PayerChange])
def payer_change_logs(connection: DbConnection, query: Annotated[logs.LogsQuery, Query()]):
    return logs.page(connection, query)


@router.get('/logs/filter-options')
def payer_change_log_options(connection: DbConnection, query: Annotated[logs.FilterQuery, Query()]):
    return logs.options(connection, query)


@router.get('/logs/export')
def payer_change_log_export(request: Request, query: Annotated[logs.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in logs.columns:
        from ...common.errors import ApiError
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(logs.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="payer-changes-{query.start_date}-to-{query.end_date}.csv"'})
