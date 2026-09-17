"""Bound SQL scopes without interpolating entity values or erasing retained history."""
from sqlalchemy import bindparam, text


def scoped_sql(sql, facility_codes=()):
    statement = text(sql)
    return statement.bindparams(bindparam("facilities", expanding=True)) if facility_codes else statement


def facility_predicate(facility_codes, column="facility_code"):
    return f" AND {column} IN :facilities" if facility_codes else ""


def parameters(start_date, end_date, facility_codes=()):
    values = {"start": start_date, "end": end_date}
    if facility_codes:
        values["facilities"] = tuple(facility_codes)
    return values
