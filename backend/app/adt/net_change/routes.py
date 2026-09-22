from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...common.errors import ErrorResponse
from ...common.tables import Page
from ...database import DbConnection
from .schemas import MonthlyLocations, MonthlyQuery, MonthlyTrend, Overview, OverviewQuery
from .service import monthly_locations, monthly_trend, overview
from . import logs

router = APIRouter(prefix='/adt/net-change', tags=['Net change'])


@router.get('/overview', response_model=Overview, responses={409: {'model': ErrorResponse}})
def net_change_overview(connection: DbConnection, query: Annotated[OverviewQuery, Query()]):
    """Census movement for one period from saved daily payer census facts.

    Movements sum across the period; census does not. Opening is read from the
    first day and closing from the last, because census is a level rather than a
    flow. Net change is the difference, which equals admissions + changes in -
    discharges - changes out over the same rows.

    The payer breakdown keeps the location filter and drops the payer filter, so
    the chart still shows the types the selection is compared against.
    """
    return overview(connection, query)


@router.get('/monthly', response_model=MonthlyTrend)
def net_change_monthly(connection: DbConnection, query: Annotated[MonthlyQuery, Query()]):
    """Monthly totals with their days nested, for the trending charts.

    Totals come from the monthly rollup; the days come from one lean aggregate
    over the daily table, because the report shows the highest and lowest day
    within each month.
    """
    return monthly_trend(connection, query)


@router.get('/monthly-locations', response_model=MonthlyLocations)
def net_change_monthly_locations(connection: DbConnection, query: Annotated[MonthlyQuery, Query()]):
    """Per-facility monthly totals, read from the calendar-month rollup.

    Net change is the summed flow rather than closing minus opening. Over a whole
    month the two are equal, and the sum needs no boundary lookup.
    """
    return monthly_locations(connection, query)


@router.get('/logs', response_model=Page[logs.Movement])
def movement_logs(connection: DbConnection, query: Annotated[logs.LogsQuery, Query()]):
    """Admissions, discharges and payer changes as one list."""
    return logs.page(connection, query)


@router.get('/logs/filter-options')
def movement_log_options(connection: DbConnection, query: Annotated[logs.FilterQuery, Query()]):
    return logs.options(connection, query)


@router.get('/logs/export')
def movement_log_export(request: Request, query: Annotated[logs.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in logs.columns:
        from ...common.errors import ApiError
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(logs.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="net-change-{query.start_date}-to-{query.end_date}.csv"'})
