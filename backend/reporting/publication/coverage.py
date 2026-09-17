"""Coverage is written with summaries, so quiet days differ from missing refreshes."""
from sqlalchemy import text

from reporting._scope import facility_predicate, parameters, scoped_sql

RULES_VERSION = "activity-v1"
# Migration marks previously committed, reconciled windows without inventing
# coverage for unprocessed dates. These metric definitions are unchanged.
COMPATIBLE_LEGACY_RULES = "legacy-published-v3"


def record_coverage(connection, dataset, scope):
    params = parameters(scope.start_date, scope.end_date, scope.facility_codes)
    params.update(dataset=dataset, rules=RULES_VERSION)
    connection.execute(scoped_sql(f"""
        INSERT INTO reporting_dataset_coverage (dataset, facility_code, date, rules_version, refreshed_at)
        SELECT :dataset, f.facility_code, d.day::date, :rules, now()
        FROM facilities f CROSS JOIN generate_series(
            CAST(:start AS date), CAST(:end AS date), interval '1 day') AS d(day)
        WHERE true{facility_predicate(scope.facility_codes, 'f.facility_code')}
        ON CONFLICT (dataset, facility_code, date) DO UPDATE
          SET rules_version=excluded.rules_version, refreshed_at=excluded.refreshed_at
    """, scope.facility_codes), params)


def coverage_bounds(connection, dataset):
    # A new population cannot be published globally until every facility has
    # coverage. Avoid regrouping all accumulated daily history after each early
    # facility batch; this existence check uses the coverage primary key.
    missing = connection.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM facilities f WHERE NOT EXISTS (
                SELECT 1 FROM reporting_dataset_coverage c
                WHERE c.dataset=:dataset AND c.facility_code=f.facility_code
                  AND c.rules_version IN (:rules, :legacy_rules)
            )
        )
    """), {"dataset": dataset, "rules": RULES_VERSION, "legacy_rules": COMPATIBLE_LEGACY_RULES})
    if missing:
        return None
    row = connection.execute(text("""
        WITH spans AS (
            SELECT facility_code, min(date) AS first_day, max(date) AS last_day, count(*) AS days
            FROM reporting_dataset_coverage WHERE dataset=:dataset AND rules_version IN (:rules, :legacy_rules)
            GROUP BY facility_code
        ) SELECT max(first_day) AS start_date, min(last_day) AS end_date,
            count(*) = (SELECT count(*) FROM facilities) AND count(*) > 0
              AND bool_and(days = last_day-first_day+1) AS ready
        FROM spans
    """), {"dataset": dataset, "rules": RULES_VERSION, "legacy_rules": COMPATIBLE_LEGACY_RULES}).mappings().one()
    if not row["ready"] or row["start_date"] > row["end_date"]:
        return None
    return row["start_date"], row["end_date"]


def update_hospital_publication(connection):
    bounds = coverage_bounds(connection, "referring_hospitals")
    if bounds is None:
        # Preserve the last complete published window during a partial catch-up.
        return
    connection.execute(text("""
        INSERT INTO adt_referring_hospital_publication (id, start_date, end_date)
        VALUES (1, :start, :end)
        ON CONFLICT (id) DO UPDATE SET start_date=excluded.start_date, end_date=excluded.end_date
    """), {"start": bounds[0], "end": bounds[1]})


def update_payer_publication(connection):
    bounds = coverage_bounds(connection, "payer_census")
    if bounds is None:
        return
    connection.execute(text("""
        UPDATE adt_payer_census_state SET ready=true, start_date=:start, end_date=:end WHERE id=1
    """), {"start": bounds[0], "end": bounds[1]})
