"""Explicit, transaction-owned refresh for any canonical source writer.

No imports from seeding or HTTP. Refresh alongside source writes in the same
transaction; committing sources first cannot provide a coherent publication.
"""
from dataclasses import replace

from data.locking import lock_source_scope

from sqlalchemy import bindparam, text

from reporting.daily.activity import refresh_reporting
from reporting.daily.census import refresh_daily_census
from reporting.daily.payer_census import refresh_payer_census
from reporting.monthly.activity import refresh_monthly_activity
from reporting.performance.hospitals import refresh_hospital_performance
from reporting.planner import ReportScope, ordered_reports, plan_changes
from reporting.publication import publish as publish_revision, require_reporting_schema
from reporting.publication.coverage import record_coverage, update_hospital_publication, update_payer_publication


def _resolved_scope(connection, scope):
    if scope.entity_ids:
        raise ValueError("Entity-scoped reporting requires resolving affected facility/date intervals first; "
                         "provide those explicitly instead of silently expanding an entity scope.")
    statement = text("SELECT facility_code, organization_id FROM facilities")
    if scope.facility_codes:
        statement = text("SELECT facility_code, organization_id FROM facilities WHERE facility_code IN :codes")
        statement = statement.bindparams(bindparam("codes", expanding=True))
    rows = connection.execute(statement, {"codes": scope.facility_codes}).mappings().all()
    found = {row["facility_code"] for row in rows}
    if scope.facility_codes and found != set(scope.facility_codes):
        raise ValueError("Unknown facilities in reporting scope: " + ", ".join(sorted(set(scope.facility_codes) - found)))
    if scope.organization_id:
        if scope.facility_codes and any(row["organization_id"] != scope.organization_id for row in rows):
            raise ValueError("Reporting facility scope crosses organization ownership.")
        rows = [row for row in rows if row["organization_id"] == scope.organization_id]
    elif len({row["organization_id"] for row in rows}) > 1:
        raise ValueError("An organization is required when reporting sources contain multiple organizations.")
    if not rows:
        raise ValueError("No facilities match the reporting scope.")
    return replace(scope, facility_codes=tuple(row["facility_code"] for row in rows))


def refresh_reports(connection, names, scope: ReportScope, *, publish=True):
    """Refresh precisely these ordered nodes; planning dependencies is explicit."""
    if not connection.in_transaction():
        raise ValueError("Reporting refresh requires an explicit caller-owned transaction.")
    names = ordered_reports(names, include_dependencies=False)
    require_reporting_schema(connection)
    scope = _resolved_scope(connection, scope)
    # Lock order matches source invalidation triggers. Holding the publication
    # row serializes revision changes; readers keep seeing committed snapshots.
    connection.execute(text("SELECT id FROM adt_reporting_state WHERE id=1 FOR UPDATE"))
    results = {}
    for name in names:
        if name == "daily_activity":
            value = refresh_reporting(connection, scope.start_date, scope.end_date,
                                      facility_codes=scope.facility_codes, publish_result=False)["daily_rows"]
        elif name == "report_results":
            results[name] = 0
            continue
        else:
            function = {"daily_census": refresh_daily_census,
                        "monthly_activity": refresh_monthly_activity,
                        "payer_census": refresh_payer_census,
                        "referring_hospitals": refresh_hospital_performance}[name]
            value = function(connection, scope.start_date, scope.end_date, facility_codes=scope.facility_codes)
        record_coverage(connection, name, scope)
        if name == "referring_hospitals":
            update_hospital_publication(connection)
        elif name == "payer_census":
            update_payer_publication(connection)
        results[name] = value
    if publish and names:
        publish_revision(connection)
    return results


def refresh_one(connection, name, start_date, end_date, *, facility_codes=(), organization_id=None, publish=True):
    return refresh_reports(connection, (name,), ReportScope(
        start_date, end_date, tuple(facility_codes), organization_id=organization_id,
    ), publish=publish)[name]


def clear_facility_history(connection, facility_code):
    """Explicit reset cleanup, separate from every ordinary reporting refresh.

    The source owner must regenerate the facility and refresh its reporting in
    this same transaction before publishing. No references or source identities
    are deleted here, and no other facility's retained history is touched.
    """
    if not connection.in_transaction():
        raise ValueError("Reporting reset cleanup requires a caller-owned transaction.")
    if not isinstance(facility_code, str) or not facility_code:
        raise ValueError("Reporting reset cleanup requires one explicit facility code.")
    if connection.scalar(text("SELECT facility_code FROM facilities WHERE facility_code=:code"),
                         {"code": facility_code}) is None:
        raise ValueError("Unknown facility in reporting reset scope.")
    require_reporting_schema(connection)
    connection.execute(text("SELECT id FROM adt_reporting_state WHERE id=1 FOR UPDATE"))
    results = {}
    for table in (
        "adt_admissions_daily", "adt_admissions_sources_daily", "adt_census_daily",
        "adt_activity_monthly", "adt_referring_hospital_monthly", "reporting_dataset_coverage",
    ):
        results[table] = connection.execute(text(f"DELETE FROM {table} WHERE facility_code=:code"),
                                            {"code": facility_code}).rowcount
    connection.execute(text("UPDATE adt_reporting_state SET ready=false WHERE id=1"))
    connection.execute(text("UPDATE adt_payer_census_state SET ready=false WHERE id=1"))
    return results


def refresh_changes(connection, changed_datasets, scope: ReportScope, *, changed_fields=None,
                    retained_through=None, publish=True):
    """Execute pure dirty-field/date propagation with one final publication."""
    tasks = plan_changes(changed_datasets, scope, changed_fields, retained_through=retained_through)
    results = {}
    for task in tasks:
        results.update(refresh_reports(connection, (task.dataset,), task.scope, publish=False))
    if publish and tasks:
        publish_revision(connection)
    return results


def refresh_from_canonical(connection, scope: ReportScope, *,
                           changed_datasets=("admissions", "discharges", "payer_changes", "stays"),
                           changed_fields=None, publish=True):
    """Publish explicitly populated canonical records to the existing read contract.

    Production ingestion writes canonical records first, then calls this in that
    same transaction. No reverse import of compatibility/demo facts occurs here.
    """
    if not connection.in_transaction():
        raise ValueError("Canonical publication requires a caller-owned transaction.")
    if not scope.organization_id or not scope.facility_codes:
        raise ValueError("Canonical publication requires an organization and explicit facility IDs.")
    require_reporting_schema(connection)
    scope = _resolved_scope(connection, scope)
    from reporting.projections.canonical import publish_legacy_read_models
    lock_source_scope(connection, scope.organization_id)
    connection.execute(text("SELECT id FROM adt_reporting_state WHERE id=1 FOR UPDATE"))
    projected = publish_legacy_read_models(connection, scope.organization_id, scope.facility_codes,
                                          scope.start_date, scope.end_date)
    refreshed = refresh_changes(connection, changed_datasets, scope, changed_fields=changed_fields,
                                publish=publish)
    return {"projections": projected, "reports": refreshed}
