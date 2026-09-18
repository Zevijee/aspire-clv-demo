from fastapi import APIRouter, Request

from ..database import DbConnection
from .schemas import DataStatus, Health
from .service import data_status

router = APIRouter(tags=['System'])


@router.get('/health', response_model=Health)
def health():
    """Process liveness; does not query the database."""
    return Health(status='ok')


@router.get('/ready', response_model=Health)
def ready(request: Request):
    """Read-only database, schema and backfill compatibility check."""
    request.app.state.database.check_ready()
    return Health(status='ready')


@router.get('/data-status', response_model=DataStatus)
def status(request: Request, connection: DbConnection):
    """Saved generator coverage; missing generators have no completion records."""
    return data_status(connection, request.app.state.settings.timezone)
