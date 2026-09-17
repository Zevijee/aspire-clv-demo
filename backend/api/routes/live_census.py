"""HTTP contracts; report work is delegated to services."""


from fastapi import APIRouter

from api.services import live_census as service

router = APIRouter(prefix='/api/v1/census', tags=['Census'])


@router.get('/live')
def live_census() -> dict:
    return service.live_census()
