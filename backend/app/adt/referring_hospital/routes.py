from typing import Annotated

from fastapi import APIRouter, Query, Request

from ...common.dates import today
from ...common.errors import ErrorResponse
from ...database import DbConnection
from .schemas import Performance, PerformanceQuery
from .service import performance

router = APIRouter(prefix='/adt/referring-hospital', tags=['Referring hospital'])


@router.get('/performance', response_model=Performance, responses={409: {'model': ErrorResponse}})
def referring_hospital_performance(request: Request, connection: DbConnection,
        query: Annotated[PerformanceQuery, Query()]):
    """Referral volume per hospital over 36 complete months.

    The period is the report's own and takes no dates: the last 3 complete
    months against the preceding 24, inside 36 months of history. The current
    month is excluded because a partial month would understate every average.

    Naming a `hospital` returns only that one, with a month series on each
    receiving facility; the list form returns every hospital with facility
    totals but no per-facility series, which is what the table shows.

    Location selection narrows the admissions counted, not which hospitals are
    listed. It is not an access-control boundary.
    """
    return performance(connection, query, today(request.app.state.settings.timezone))
