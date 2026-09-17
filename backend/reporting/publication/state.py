"""The legacy reporting revision is advanced only with committed complete writes.

PostgreSQL MVCC keeps the prior committed summaries available while refreshing.
This is an atomic current publication, not retained historical publication rows.
"""
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from data.models.admissions import admissions
from data.models.admissions_reporting import cache, state
from reporting.publication.coverage import coverage_bounds


def require_reporting_schema(connection):
    missing = [name for name in (
        "adt_reporting_state", "adt_report_cache", "adt_admissions_daily",
        "adt_admissions_sources_daily", "adt_census_daily", "adt_activity_monthly",
        "adt_referring_hospital_monthly", "adt_referring_hospital_publication", "reporting_dataset_coverage",
    ) if connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is None]
    if missing:
        raise RuntimeError("Reporting schema is not installed (" + ", ".join(missing)
                           + "). Apply the versioned database migrations separately.")


def publish(connection):
    """Caller owns transaction. Failure rolls back both rows and publication."""
    count = connection.scalar(select(func.count()).select_from(admissions))
    bounds = coverage_bounds(connection, "daily_activity")
    connection.execute(insert(state).values(id=1, revision=0, ready=False, admission_count=0)
                       .on_conflict_do_nothing(index_elements=[state.c.id]))
    revision = connection.scalar(state.update().where(state.c.id == 1).values(
        revision=state.c.revision + 1, ready=bounds is not None, admission_count=count,
        first_date=bounds[0] if bounds else None, latest_date=bounds[1] if bounds else None,
        refreshed_at=func.now(),
    ).returning(state.c.revision))
    connection.execute(cache.delete())
    return revision
