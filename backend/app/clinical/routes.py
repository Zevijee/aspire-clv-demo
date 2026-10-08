from typing import Annotated

from fastapi import APIRouter, Query

from ..common.errors import ErrorResponse
from ..database import DbConnection
from . import hospital_transfers

router = APIRouter(prefix='/clinical', tags=['Clinical'])


@router.get('/hospital-transfers', response_model=hospital_transfers.HospitalTransfers,
    responses={409: {'model': ErrorResponse}})
def hospital_transfers_report(connection: DbConnection,
        query: Annotated[hospital_transfers.TransfersQuery, Query()]):
    """Every facility's hospital transfers in the range: how many, how many within
    30 days of admission, their summed days since admission, the rehospitalizations
    among them, the resident days the rate per 1,000 divides by, the prior period's
    count, and the counts by payer and reason. payer_types and reasons filter it."""
    return hospital_transfers.hospital_transfers(connection, query)
