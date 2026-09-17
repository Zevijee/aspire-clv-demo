"""Monthly totals derived from retained daily rows, never summed census values."""
from reporting._scope import facility_predicate, parameters, scoped_sql


def refresh_monthly_activity(connection, start_date, end_date, *, facility_codes=()):
    if start_date > end_date:
        raise ValueError("Reporting date range is reversed.")
    first_month, last_month = start_date.replace(day=1), end_date.replace(day=1)
    clause = facility_predicate(facility_codes)
    params = parameters(first_month, last_month, facility_codes)
    connection.execute(scoped_sql(f"""
        DELETE FROM adt_activity_monthly WHERE month BETWEEN :start AND :end{clause}
    """, facility_codes), params)
    # A correction to one day rebuilds its entire month from retained daily data.
    result = connection.execute(scoped_sql(f"""
        INSERT INTO adt_activity_monthly
            (facility_code, month, opening_census, closing_census, admissions, discharges, net_change)
        SELECT facility_code, date_trunc('month', census_date)::date,
               (array_agg(opening_census ORDER BY census_date))[1],
               (array_agg(closing_census ORDER BY census_date DESC))[1],
               sum(admissions), sum(discharges), sum(admissions-discharges)
        FROM adt_census_daily WHERE census_date >= :start
          AND census_date < CAST(:end AS date) + interval '1 month'{clause}
        GROUP BY facility_code, date_trunc('month', census_date)::date
    """, facility_codes), params)
    return result.rowcount
