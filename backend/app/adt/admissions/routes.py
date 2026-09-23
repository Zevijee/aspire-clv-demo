from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...common.errors import ErrorResponse
from ...database import DbConnection
from .schemas import MonthlyLocations, MonthlyQuery, MonthlyTrend, Overview, OverviewQuery
from .service import monthly_locations, monthly_trend, overview
from . import logs
from ...common.tables import Page

router = APIRouter(prefix='/adt/admissions', tags=['Admissions'])


@router.get('/overview', response_model=Overview, responses={409: {'model': ErrorResponse}})
def admissions_overview(connection: DbConnection, query: Annotated[OverviewQuery, Query()]):
    """One period from saved daily summaries. Request the prior period separately.

    Payer/source chart breakdowns exclude their own filter, while totals,
    location rows, hospitals and daily counts apply both filters.
    """
    return overview(connection, query)


@router.get('/monthly', response_model=MonthlyTrend, responses={409: {'model': ErrorResponse}})
def admissions_monthly(connection: DbConnection, query: Annotated[MonthlyQuery, Query()]):
    """Monthly admissions with their days nested, narrowed by referral source.

    The Monthly ADT report reads census from the payer census rollup, which has
    no source dimension and cannot have one -- a resident's presence in a bed is
    not divisible by where they arrived from. Admissions are, because
    `source_type` sits at the grain of the daily admission facts, so this reads
    those instead. Both tables report identical monthly admissions.

    The days travel with each month because the report shows its highest and
    lowest day, which no month-grain table can answer. `by_source` drops the
    source filter so the control still shows what the selection is compared
    against.
    """
    return monthly_trend(connection, query)


@router.get('/monthly-locations', response_model=MonthlyLocations,
    responses={409: {'model': ErrorResponse}})
def admissions_monthly_locations(connection: DbConnection,
        query: Annotated[MonthlyQuery, Query()]):
    """Per-facility monthly admissions, under the same filters as `/monthly`.

    It shares a screen with that trend, so it has to narrow identically: an
    unfiltered location table beside a filtered chart is worse than no filter.
    """
    return monthly_locations(connection, query)


@router.get('/logs', response_model=Page[logs.Admission])
def admission_logs(connection: DbConnection, query: Annotated[logs.LogsQuery, Query()]):
    return logs.page(connection, query)


@router.get('/logs/filter-options')
def admission_log_options(connection: DbConnection, query: Annotated[logs.FilterQuery, Query()]):
    return logs.options(connection, query)


@router.get('/logs/export')
def admission_log_export(request: Request, query: Annotated[logs.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in logs.columns:
        from ...common.errors import ApiError
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(logs.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="admissions-{query.start_date}-to-{query.end_date}.csv"'})
