"""Refresh scoped daily admissions summaries from persisted admission events."""
from sqlalchemy import func, select, text

from data.models.admissions_reporting import cache, daily, metadata, sources, state
from reporting._scope import facility_predicate, parameters, scoped_sql
from reporting.publication import publish, require_reporting_schema
from reporting.publication.coverage import record_coverage
from reporting.planner import ReportScope


def refresh_reporting(connection, start_date=None, end_date=None, *, facility_codes=(), publish_result=True):
    """Replace only the selected dates/facilities; the caller owns the transaction."""
    if (start_date is None) != (end_date is None):
        raise ValueError("Provide both start_date and end_date for a scoped refresh.")
    if start_date is None:
        start_date, end_date = connection.execute(text(
            "SELECT min(admission_date), max(admission_date) FROM adt_admissions"
        )).one()
        if start_date is None:
            raise ValueError("No source window is available. Supply an explicit covered date range.")
    if start_date > end_date:
        raise ValueError("Reporting date range is reversed.")
    if publish_result:
        require_reporting_schema(connection)
    clause = facility_predicate(facility_codes)
    params = parameters(start_date, end_date, facility_codes)
    for name in ("adt_admissions_daily", "adt_admissions_sources_daily"):
        connection.execute(scoped_sql(
            f"DELETE FROM {name} WHERE admission_date BETWEEN :start AND :end{clause}", facility_codes
        ), params)
    connection.execute(scoped_sql(f"""
        INSERT INTO adt_admissions_daily
            (admission_date, facility_code, payer_type, total_admissions,
             readmission_count, readmission_within_30_days_count)
        SELECT admission_date, facility_code, payer_type, count(*),
               count(*) FILTER (WHERE is_readmission),
               count(*) FILTER (WHERE readmission_days_since_prior <= 30)
        FROM adt_admissions WHERE admission_date BETWEEN :start AND :end{clause}
        GROUP BY admission_date, facility_code, payer_type
    """, facility_codes), params)
    connection.execute(scoped_sql(f"""
        INSERT INTO adt_admissions_sources_daily
            (admission_date, facility_code, payer_type, admission_source_type,
             admission_source_name, admission_count)
        SELECT admission_date, facility_code, payer_type, admission_source_type,
               admission_source_name, count(*)
        FROM adt_admissions WHERE admission_date BETWEEN :start AND :end{clause}
        GROUP BY admission_date, facility_code, payer_type, admission_source_type, admission_source_name
    """, facility_codes), params)
    totals = connection.execute(scoped_sql(f"""
        SELECT count(*) AS count, count(*) FILTER (WHERE is_readmission) AS readmissions,
               count(*) FILTER (WHERE readmission_days_since_prior <= 30) AS within_30
        FROM adt_admissions WHERE admission_date BETWEEN :start AND :end{clause}
    """, facility_codes), params).mappings().one()
    summary = connection.execute(scoped_sql(f"""
        SELECT coalesce(sum(total_admissions), 0), coalesce(sum(readmission_count), 0),
               coalesce(sum(readmission_within_30_days_count), 0)
        FROM adt_admissions_daily WHERE admission_date BETWEEN :start AND :end{clause}
    """, facility_codes), params).one()
    source_total = connection.scalar(scoped_sql(f"""
        SELECT coalesce(sum(admission_count), 0) FROM adt_admissions_sources_daily
        WHERE admission_date BETWEEN :start AND :end{clause}
    """, facility_codes), params)
    if tuple(summary) != (totals["count"], totals["readmissions"], totals["within_30"]) or source_total != totals["count"]:
        raise ValueError("Scoped daily/source reporting totals do not reconcile to admissions.")
    if publish_result:
        record_coverage(connection, "daily_activity", ReportScope(start_date, end_date, tuple(facility_codes)))
        publish(connection)
    count = connection.scalar(scoped_sql(f"""
        SELECT count(*) FROM adt_admissions_daily WHERE admission_date BETWEEN :start AND :end{clause}
    """, facility_codes), params)
    return {"admissions": totals["count"], "daily_rows": count}


# Kept for old imports; schema preparation is now a separate migration operation.
ensure_reporting_schema = require_reporting_schema
