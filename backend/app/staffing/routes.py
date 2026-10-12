from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..common.dates import DateRange
from ..common.errors import ApiError, ErrorResponse
from ..database import DbConnection
from . import employees, ppd

router = APIRouter(prefix='/staffing', tags=['Staffing'])


@router.get('/employees', response_model=employees.EmployeesPage, responses={409: {'model': ErrorResponse}})
def employees_page(connection: DbConnection, query: Annotated[employees.EmployeesQuery, Query()]):
    """PPD's Employees tab: every staff member with hours between `start_date`
    and `end_date` in the repeated `roles` (or all), paged: their shifts, hours,
    average shift, hours a week, overtime, hours per patient day at their
    facility, average rate and wages. Only the last 120 days of hours are kept;
    the range is clamped to them and the response says which days exist."""
    return employees.page(connection, query)


@router.get('/employees/filter-options')
def employee_options(connection: DbConnection, query: Annotated[employees.FilterQuery, Query()]):
    return employees.options(connection, query)


@router.get('/employees/export')
def employee_export(request: Request, query: Annotated[employees.EmployeesQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in employees.SORTABLE:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(employees.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="ppd-employees.csv"'})


@router.get('/ppd', response_model=ppd.PpdReport, responses={409: {'model': ErrorResponse}})
def ppd_report(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Every facility's census days in the range and, for each staffing role, its
    hours worked, target hours, hours over and under the daily target, wages and
    the wages of the hours over target, for the page to add up at any level."""
    return ppd.ppd(connection, query)


@router.get('/ppd/trend', response_model=ppd.PpdTrend, responses={409: {'model': ErrorResponse}})
def ppd_trend(connection: DbConnection, query: Annotated[ppd.TrendQuery, Query()]):
    """Every facility's hours worked, target hours and census for each day of the
    range over the repeated `roles` (or all), as arrays in date order, for the
    Trending tab to add up at any drilldown level and divide day by day."""
    return ppd.trend(connection, query)


@router.get('/ppd/daily', response_model=ppd.DailyPpd, responses={409: {'model': ErrorResponse}})
def ppd_daily(connection: DbConnection, query: Annotated[ppd.DailyPpdQuery, Query()]):
    """Each day's census, hours worked and target hours over the given roles and
    facilities, or all of them, for the PPD trend."""
    return ppd.daily(connection, query)
