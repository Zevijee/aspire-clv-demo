"""HTTP contracts; report work is delegated to services."""

from typing import Any

from fastapi import APIRouter

from api.services import facilities as service

router = APIRouter(prefix='/api/v1/facilities', tags=['facilities'])


@router.get('')
def list_facilities() -> list[dict[str, Any]]:
    return service.list_facilities()
