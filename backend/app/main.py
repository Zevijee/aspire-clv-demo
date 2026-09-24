"""FastAPI composition root. Register implemented feature routers here."""
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .common.errors import ApiError, DatabaseNotReady, ErrorResponse, ValidationErrorResponse
from .config import Settings
from .database import Database
from .auth.routes import require_user, router as auth_router
from .reference.routes import router as reference_router
from .system.routes import router as system_router
from .adt.admissions.routes import router as admissions_router
from .adt.discharges.routes import router as discharges_router
from .adt.payer_changes.routes import router as payer_changes_router
from .adt.net_change.routes import router as net_change_router
from .adt.referring_hospital.routes import router as referring_hospital_router
from .census.routes import router as census_router

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
    # Outermost, so the session is decoded before any route or dependency runs.
    app.add_middleware(SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie='clearview_session', https_only=settings.session_https_only,
        same_site='lax', max_age=settings.session_minutes * 60)
    # allow_credentials is required for the browser to send the session cookie at
    # all, and a credentialed request may not use a wildcard origin -- so the
    # origin list is now load bearing rather than advisory. POST is allowed for
    # login, refresh and logout only; the reports remain GET.
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=True, allow_methods=['GET', 'POST'],
        allow_headers=['Accept', 'Content-Type'])

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

    # system stays open: /health and /ready are liveness, not data, and an uptime
    # monitor should not need a password to watch the site.
    app.include_router(system_router, prefix='/api/v1')
    app.include_router(auth_router, prefix='/api/v1')
    # Everything below reads resident data. The dependency is attached to the
    # router rather than to each route, so a new endpoint is protected by being
    # added rather than by someone remembering to guard it.
    locked = [Depends(require_user)]
    app.include_router(reference_router, prefix='/api/v1', dependencies=locked)
    app.include_router(admissions_router, prefix='/api/v1', dependencies=locked)
    app.include_router(discharges_router, prefix='/api/v1', dependencies=locked)
    app.include_router(payer_changes_router, prefix='/api/v1', dependencies=locked)
    app.include_router(net_change_router, prefix='/api/v1', dependencies=locked)
    app.include_router(referring_hospital_router, prefix='/api/v1', dependencies=locked)
    app.include_router(census_router, prefix='/api/v1', dependencies=locked)
    return app
