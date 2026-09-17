"""Validate and publish payer-interval coverage without generating new intervals."""
from reporting._scope import facility_predicate, parameters, scoped_sql


def refresh_payer_census(connection, start_date, end_date, *, facility_codes=()):
    """Intervals must already be projected from canonical or reconciled seed sources."""
    clause = facility_predicate(facility_codes)
    params = parameters(start_date, end_date, facility_codes)
    result = connection.execute(scoped_sql(f"""
        WITH scoped_periods AS MATERIALIZED (
            SELECT facility_code, start_date, end_date FROM adt_payer_periods
            WHERE start_date <= :end AND (end_date IS NULL OR end_date >= :start){clause}
        ), initial AS (
            SELECT facility_code, count(*) AS n FROM scoped_periods
            WHERE start_date < :start AND (end_date IS NULL OR end_date >= :start)
            GROUP BY facility_code
        ), changes AS (
            SELECT facility_code, start_date AS day, count(*) AS delta FROM scoped_periods
            WHERE start_date BETWEEN :start AND :end GROUP BY 1, 2
            UNION ALL
            SELECT facility_code, end_date AS day, -count(*) AS delta FROM scoped_periods
            WHERE end_date BETWEEN :start AND :end GROUP BY 1, 2
        ), daily_changes AS (
            SELECT facility_code, day, sum(delta) AS delta FROM changes GROUP BY 1, 2
        ), balances AS (
            SELECT c.facility_code, c.census_date, c.closing_census,
                coalesce(i.n, 0) + sum(coalesce(d.delta, 0)) OVER (
                    PARTITION BY c.facility_code ORDER BY c.census_date ROWS UNBOUNDED PRECEDING
                ) AS payer_census
            FROM adt_census_daily c
            LEFT JOIN initial i USING (facility_code)
            LEFT JOIN daily_changes d ON d.facility_code=c.facility_code AND d.day=c.census_date
            WHERE c.census_date BETWEEN :start AND :end{facility_predicate(facility_codes, 'c.facility_code')}
        ) SELECT count(*) AS days, count(*) FILTER (WHERE closing_census <> payer_census) AS mismatches
        FROM balances
    """, facility_codes), params).mappings().one()
    facility_count = len(facility_codes) if facility_codes else connection.scalar(scoped_sql("SELECT count(*) FROM facilities"))
    expected = facility_count * ((end_date - start_date).days + 1)
    if result["days"] != expected:
        raise ValueError("Payer census cannot publish while daily census coverage is incomplete.")
    if result["mismatches"]:
        raise ValueError("Payer intervals do not reconcile with census in the requested scope.")
    return result["days"]
