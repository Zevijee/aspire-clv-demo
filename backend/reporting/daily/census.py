"""Compute complete daily census rows without simulating resident history."""
from sqlalchemy import text

from reporting._scope import facility_predicate, parameters, scoped_sql


def refresh_daily_census(connection, start_date, end_date, *, facility_codes=()):
    if start_date > end_date:
        raise ValueError("Reporting date range is reversed.")
    clause = facility_predicate(facility_codes)
    params = parameters(start_date, end_date, facility_codes)
    connection.execute(scoped_sql(
        f"DELETE FROM adt_census_daily WHERE census_date BETWEEN :start AND :end{clause}", facility_codes
    ), params)
    result = connection.execute(scoped_sql(f"""
        INSERT INTO adt_census_daily
            (facility_code, census_date, opening_census, closing_census, admissions, discharges)
        WITH dates AS (
            SELECT generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day')::date AS day
        ), opening AS (
            SELECT facility_code, count(*) AS n FROM adt_resident_stays
            WHERE start_date < :start AND (end_date IS NULL OR end_date >= :start){clause}
            GROUP BY facility_code
        ), arrivals AS (
            SELECT facility_code, admission_date AS day, count(*) AS n FROM adt_admissions
            WHERE admission_date BETWEEN :start AND :end{clause} GROUP BY 1, 2
        ), departures AS (
            SELECT facility_code, discharge_date AS day, count(*) AS n FROM adt_discharges
            WHERE discharge_date BETWEEN :start AND :end{clause} GROUP BY 1, 2
        ), movements AS (
            SELECT f.facility_code, d.day, coalesce(o.n, 0) AS initial,
                   coalesce(a.n, 0) AS admitted, coalesce(x.n, 0) AS discharged
            FROM facilities f CROSS JOIN dates d
            LEFT JOIN opening o USING (facility_code)
            LEFT JOIN arrivals a ON a.facility_code=f.facility_code AND a.day=d.day
            LEFT JOIN departures x ON x.facility_code=f.facility_code AND x.day=d.day
            WHERE true{facility_predicate(facility_codes, 'f.facility_code')}
        ), totals AS (
            SELECT *, initial + sum(admitted-discharged) OVER (
                PARTITION BY facility_code ORDER BY day ROWS UNBOUNDED PRECEDING) AS closing
            FROM movements
        ) SELECT facility_code, day, closing-admitted+discharged, closing, admitted, discharged FROM totals
    """, facility_codes), params)
    # Report global coverage only across dates present for every facility. A partial
    # facility catch-up must not advertise its newer end date for the whole estate.
    connection.execute(text("""
        WITH coverage AS (
            SELECT facility_code, min(census_date) AS first_day, max(census_date) AS last_day,
                   count(*) AS days
            FROM adt_census_daily GROUP BY facility_code
        ), bounds AS (
            SELECT max(first_day) AS first_day, min(last_day) AS last_day,
                   count(*) = (SELECT count(*) FROM facilities) AND
                   bool_and(days = last_day - first_day + 1) AS complete
            FROM coverage
        ) UPDATE adt_census_state s SET
            ready=coalesce(b.complete AND b.first_day <= b.last_day, false),
            start_date=b.first_day, end_date=b.last_day
        FROM bounds b WHERE s.id=1
    """))
    return result.rowcount
