from typing import Annotated

from fastapi import APIRouter, Query

from ..common.dates import DateRange
from ..common.errors import ErrorResponse
from ..database import DbConnection
from . import ppd

router = APIRouter(prefix='/staffing', tags=['Staffing'])


@router.get('/ppd', response_model=ppd.PpdReport, responses={409: {'model': ErrorResponse}})
def ppd_report(connection: DbConnection, query: Annotated[DateRange, Query()]):
    """Every facility's census days in the range and, for each staffing role, its
    hours worked, target hours, hours over and under the daily target, wages and
    the wages of the hours over target, for the page to add up at any level."""
    return ppd.ppd(connection, query)


@router.get('/ppd/daily', response_model=ppd.DailyPpd, responses={409: {'model': ErrorResponse}})
def ppd_daily(connection: DbConnection, query: Annotated[ppd.DailyPpdQuery, Query()]):
    """Each day's census, hours worked and target hours over the given roles and
    facilities, or all of them, for the PPD trend."""
    return ppd.daily(connection, query)
