from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..common.dates import DateRange
from ..common.errors import ApiError, ErrorResponse
from ..database import DbConnection
from . import agency, employees, overtime, overview, ppd

router = APIRouter(prefix='/staffing', tags=['Staffing'])


@router.get('/overview', response_model=overview.OverviewReport, responses={409: {'model': ErrorResponse}})
def overview_report(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Staffing Overview: every facility's census days, hours worked against
    budget, overtime, holiday, agency and classroom and floor orientation hours,
    and the straight-time pay, premiums, orientation pay and bonuses that make
    up labour cost, every
    role together, between `start_date` and `end_date`, for the page to add up
    at any level and divide once."""
    return overview.report(connection, query)


@router.get('/employees/packed', response_model=employees.PackedEmployees, responses={409: {'model': ErrorResponse}})
def employees_packed(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Every employee with hours between `start_date` and `end_date`, compactly:
    what a Staffing Overview export carries, so its employee windows work in the
    file. Labels repeated across rows are listed once and referred to by index."""
    return employees.packed(connection, query)


@router.get('/employees', response_model=employees.EmployeesPage, responses={409: {'model': ErrorResponse}})
def employees_page(connection: DbConnection, query: Annotated[employees.EmployeesQuery, Query()]):
    """The Staffing Overview's Employees tab: every employee with hours between `start_date`
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
        headers={'Content-Disposition': 'attachment; filename="hppd-employees.csv"'})


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


@router.get('/agency', response_model=agency.AgencyReport, responses={409: {'model': ErrorResponse}})
def agency_report(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Agency vs In-house: every facility's hours and wages between `start_date`
    and `end_date` split between agency staff and the facility's own, per role,
    from the per-person daily hours, with what the agency hours cost over the
    same hours at that facility and role's in-house rate. Only the last 120 days
    of hours are kept; the range is clamped to them and the response says which
    days exist."""
    return agency.report(connection, query)


@router.get('/ppd-cost/trend', response_model=ppd.PpdCostTrend, responses={409: {'model': ErrorResponse}})
def ppd_cost_trend(connection: DbConnection, query: Annotated[ppd.TrendQuery, Query()]):
    """PPD cost's Trending tab: every facility's labour cost, budget and closing
    census for each day of the range, over the repeated `roles` (or every role),
    as arrays in `dates` order, to add up at any drilldown level and divide day
    by day."""
    return ppd.cost_trend(connection, query)


@router.get('/agency/trend', response_model=agency.AgencyTrend, responses={409: {'model': ErrorResponse}})
def agency_trend(connection: DbConnection, query: Annotated[ppd.TrendQuery, Query()]):
    """Agency vs In-house's Trending tab: every facility's agency hours, in-house
    hours and agency wages for each day of the range over the repeated `roles`
    (or all), as arrays in date order, for the page to add up at any drilldown
    level and read day by day. The range is clamped to the 120 days of hours
    kept."""
    return agency.trend(connection, query)


@router.get('/agency/logs', response_model=agency.AgencyLogsPage, responses={409: {'model': ErrorResponse}})
def agency_logs(connection: DbConnection, query: Annotated[agency.LogsQuery, Query()]):
    """Agency vs In-house's Logs tab: one row per agency person per day worked
    between `start_date` and `end_date` in the repeated `roles` (or all), paged,
    sorted and filtered: who, at which facility and role, the hours, the rate
    and the wages. The range is clamped to the 120 days of hours kept."""
    return agency.logs(connection, query)


@router.get('/agency/logs/filter-options')
def agency_log_options(connection: DbConnection, query: Annotated[agency.LogsFilterQuery, Query()]):
    return agency.log_options(connection, query)


@router.get('/agency/logs/export')
def agency_log_export(request: Request, query: Annotated[agency.LogsQuery, Query()]):
    if query.sort is not None and query.sort not in agency.SORTABLE:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(agency.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="agency-shifts.csv"'})


@router.get('/overtime', response_model=overtime.OvertimeReport, responses={409: {'model': ErrorResponse}})
def overtime_report(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Overtime: every facility's hours, wages, overtime hours (over 40 a week
    per person, from each day's stored share), the overtime's straight-time
    pay, and the people who worked and who had overtime, per role, between
    `start_date` and `end_date`, for the page to add up at any level. The range
    is clamped to the 120 days of hours kept."""
    return overtime.report(connection, query)


@router.get('/overtime/trend', response_model=overtime.OvertimeTrend, responses={409: {'model': ErrorResponse}})
def overtime_trend(connection: DbConnection, query: Annotated[ppd.TrendQuery, Query()]):
    """Overtime's Trending tab: every facility's hours, overtime hours and the
    overtime's straight-time pay for each day of the range over the repeated
    `roles` (or all), as arrays in date order."""
    return overtime.trend(connection, query)


@router.get('/overtime/logs', response_model=overtime.OvertimeLogsPage, responses={409: {'model': ErrorResponse}})
def overtime_logs(connection: DbConnection, query: Annotated[overtime.LogsQuery, Query()]):
    """Overtime's Logs tab: one row per person per day with overtime between
    `start_date` and `end_date` in the repeated `roles` (or all), paged, sorted
    and filtered: who, where, the day's hours and overtime, the rate and what
    time-and-a-half would add."""
    return overtime.logs(connection, query)


@router.get('/overtime/logs/filter-options')
def overtime_log_options(connection: DbConnection, query: Annotated[overtime.LogsFilterQuery, Query()]):
    return overtime.log_options(connection, query)


@router.get('/overtime/logs/export')
def overtime_log_export(request: Request, query: Annotated[overtime.LogsQuery, Query()]):
    if query.sort is not None and query.sort not in overtime.SORTABLE:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(overtime.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="overtime-shifts.csv"'})


@router.get('/ppd/daily', response_model=ppd.DailyPpd, responses={409: {'model': ErrorResponse}})
def ppd_daily(connection: DbConnection, query: Annotated[ppd.DailyPpdQuery, Query()]):
    """Each day's census, hours worked and target hours over the given roles and
    facilities, or all of them, for the PPD trend."""
    return ppd.daily(connection, query)
