"""Reference data shared by all reporting modules."""
from typing import Annotated

from fastapi import APIRouter, Query

from ..common.tables import Page
from ..database import DbConnection
from . import service
from .schemas import FacilityLocation, LocationQuery, Payer, PayerQuery

router = APIRouter(prefix='/reference', tags=['Reference'])


@router.get('/locations', response_model=Page[FacilityLocation])
def locations(connection: DbConnection, query: Annotated[LocationQuery, Query()]):
    """Saved facility IDs with their state/portfolio/region paths; paginated."""
    return service.locations(connection, query)


@router.get('/payers', response_model=Page[Payer])
def payers(connection: DbConnection, query: Annotated[PayerQuery, Query()]):
    """Saved payer IDs and classifications; filters describe catalog values."""
    return service.payer_catalog(connection, query)
