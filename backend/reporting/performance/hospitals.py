"""Hospital monthly summaries shared by production ingestion and the demo seeder."""
from sqlalchemy import text

from reporting._scope import facility_predicate, parameters, scoped_sql


def refresh_hospital_performance(connection, start_date, end_date, *, facility_codes=()):
    """Refresh affected whole months; hospital identity/hierarchy is never fabricated."""
    if start_date > end_date:
        raise ValueError("Reporting date range is reversed.")
    first_month, last_month = start_date.replace(day=1), end_date.replace(day=1)
    clause = facility_predicate(facility_codes)
    params = parameters(first_month, last_month, facility_codes)
    # A production hospital can refer across regions. Same-region distribution is
    # a demo scenario choice, not a validity constraint on real referrals.
    invalid = connection.scalar(scoped_sql(f"""
        SELECT count(*) FROM adt_admissions a
        LEFT JOIN adt_referring_hospitals h ON h.hospital = a.admission_source_name
        WHERE a.admission_source_type = 'Hospital' AND h.hospital IS NULL
          AND a.admission_date >= :start
          AND a.admission_date < CAST(:end AS date) + interval '1 month'
          {facility_predicate(facility_codes, 'a.facility_code')}
    """, facility_codes), params)
    if invalid:
        raise ValueError("Hospital admissions contain unrecognized hospital identities; map them before refresh.")
    connection.execute(scoped_sql(f"""
        DELETE FROM adt_referring_hospital_monthly WHERE month BETWEEN :start AND :end{clause}
    """, facility_codes), params)
    # Relationships span retained source history. Inactive combinations keep an
    # explicit zero in each refreshed month instead of disappearing from trends.
    result = connection.execute(scoped_sql(f"""
        INSERT INTO adt_referring_hospital_monthly
            (month, hospital, facility_code, payer_type, admissions, readmissions, readmissions_within_30)
        WITH facts AS (
            SELECT date_trunc('month', admission_date)::date AS month,
                   admission_source_name AS hospital, facility_code, payer_type,
                   count(*) AS admissions, count(*) FILTER (WHERE is_readmission) AS readmissions,
                   count(*) FILTER (WHERE readmission_days_since_prior <= 30) AS readmissions_within_30
            FROM adt_admissions
            WHERE admission_source_type = 'Hospital' AND admission_date >= :start
              AND admission_date < CAST(:end AS date) + interval '1 month'{clause}
            GROUP BY 1, 2, 3, 4
        ), relationships AS (
            SELECT DISTINCT admission_source_name AS hospital, facility_code, payer_type
            FROM adt_admissions WHERE admission_source_type = 'Hospital'{clause}
        ), months AS (
            SELECT generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 month')::date AS month
        )
        SELECT m.month, r.hospital, r.facility_code, r.payer_type,
               coalesce(f.admissions, 0), coalesce(f.readmissions, 0), coalesce(f.readmissions_within_30, 0)
        FROM relationships r CROSS JOIN months m
        LEFT JOIN facts f USING (month, hospital, facility_code, payer_type)
    """, facility_codes), params)
    totals = connection.scalar(scoped_sql(f"""
        SELECT coalesce(sum(admissions), 0) FROM adt_referring_hospital_monthly
        WHERE month BETWEEN :start AND :end{clause}
    """, facility_codes), params)
    source_total = connection.scalar(scoped_sql(f"""
        SELECT count(*) FROM adt_admissions WHERE admission_source_type = 'Hospital'
          AND admission_date >= :start AND admission_date < CAST(:end AS date) + interval '1 month'{clause}
    """, facility_codes), params)
    if totals != source_total:
        raise ValueError("Scoped hospital monthly totals do not reconcile to admissions.")
    return result.rowcount
