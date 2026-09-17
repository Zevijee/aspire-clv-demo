"""HTTP composition; importing the application does not open a database connection."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import ProgrammingError

from api.queries.errors import ReportQueryError
from api.routes import (
    adt_admissions,
    adt_discharges,
    adt_movement_logs,
    adt_net_change,
    adt_payer_changes,
    facilities,
    live_census,
    table_filters,
)
from api.schemas.system import HealthResponse
from common.config import get_settings
from reporting.results.cache import ReportingUnavailableError


def get_health() -> HealthResponse:
    """Local process readiness; no database read, migration, or refresh."""
    return HealthResponse(status="ok", service="aspire-analytics-api")


async def report_query_error(request: Request, error: ReportQueryError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})


async def reporting_unavailable(request: Request, error: ReportingUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


async def schema_unavailable(request: Request, error: ProgrammingError) -> JSONResponse:
    """Explain unapplied schemas without treating unrelated SQL bugs as migrations."""
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    if sqlstate not in {"42P01", "42703"}:
        raise error
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "The database schema is not ready for this application version. "
                "Apply the prepared migrations with python -m data.migrations upgrade "
                "before loading reports. No migration was applied automatically."
            )
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Aspire Analytics API",
        version="0.1.0",
        description="Local reporting API for the Aspire SNF analytics demo.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.add_exception_handler(ReportQueryError, report_query_error)
    application.add_exception_handler(ReportingUnavailableError, reporting_unavailable)
    application.add_exception_handler(ProgrammingError, schema_unavailable)
    for module in (
        facilities,
        live_census,
        adt_admissions,
        adt_discharges,
        adt_payer_changes,
        adt_net_change,
        adt_movement_logs,
        table_filters,
    ):
        application.include_router(module.router)
    application.get("/api/v1/health", tags=["system"])(get_health)
    return application


app = create_app()
