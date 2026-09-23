"""FastAPI composition root. Register implemented feature routers here."""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .common.errors import ApiError, DatabaseNotReady, ErrorResponse, ValidationErrorResponse
from .config import Settings
from .database import Database
from .reference.routes import router as reference_router
from .system.routes import router as system_router
from .adt.admissions.routes import router as admissions_router
from .adt.discharges.routes import router as discharges_router
from .adt.payer_changes.routes import router as payer_changes_router
from .adt.net_change.routes import router as net_change_router
from .adt.referring_hospital.routes import router as referring_hospital_router

logger = logging.getLogger('aspire.api')


def create_app() -> FastAPI:
    settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings)
        app.state.database = database
        try:
            try:
                await run_in_threadpool(database.check_ready)
            except (SQLAlchemyError, DatabaseNotReady):
                raise RuntimeError('Database is not ready. Check DATABASE_URL and run '
                    'python manage.py upgrade from sandbox-data before starting the API.') from None
            yield
        finally:
            await run_in_threadpool(database.close)

    app = FastAPI(
        title='Aspire Analytics API', version='0.1.0', lifespan=lifespan,
        description='Shared reporting API. Database migrations and generation run separately in sandbox-data.',
        responses={400: {'model': ErrorResponse}, 422: {'model': ValidationErrorResponse},
            503: {'model': ErrorResponse}},
    )
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=False, allow_methods=['GET'], allow_headers=['Accept', 'Content-Type', 'Authorization'])

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        return JSONResponse(status_code=error.status_code, content=dict(code=error.code, detail=error.detail),
            headers={'Retry-After': '5'} if error.status_code == 503 else None)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        # Do not log exception strings, SQL parameters, URLs or resident data.
        logger.error('Database operation failed (%s)', type(error).__name__)
        return JSONResponse(status_code=503, content=dict(code='database_unavailable',
            detail='The database request could not complete. Please retry.'), headers={'Retry-After': '5'})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Keep field locations and explanations, omit echoed input values.
        issues = [dict(loc=list(item['loc']), msg=item['msg'], type=item['type']) for item in error.errors()]
        return JSONResponse(status_code=422, content=dict(code='invalid_request',
            detail='Invalid request parameters.', errors=issues))

    app.include_router(system_router, prefix='/api/v1')
    app.include_router(reference_router, prefix='/api/v1')
    app.include_router(admissions_router, prefix='/api/v1')
    app.include_router(discharges_router, prefix='/api/v1')
    app.include_router(payer_changes_router, prefix='/api/v1')
    app.include_router(net_change_router, prefix='/api/v1')
    app.include_router(referring_hospital_router, prefix='/api/v1')
    return app
