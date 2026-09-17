"""Source-load publication barrier and facility-scoped reporting indexes."""
from sqlalchemy import text
from data.models.reporting_publication import loads


def upgrade(connection):
    loads.create(connection, checkfirst=True)
    for name, table, columns in (
        ('ix_payer_periods_facility_start', 'adt_payer_periods', 'facility_code, start_date'),
        ('ix_payer_periods_facility_end', 'adt_payer_periods', 'facility_code, end_date'),
        ('ix_stays_facility_start', 'adt_resident_stays', 'facility_code, start_date'),
        ('ix_discharges_facility_date', 'adt_discharges', 'facility_code, discharge_date'),
        ('ix_admissions_daily_facility_date', 'adt_admissions_daily', 'facility_code, admission_date'),
        ('ix_sources_daily_facility_date', 'adt_admissions_sources_daily', 'facility_code, admission_date'),
        ('ix_hospital_monthly_facility_month', 'adt_referring_hospital_monthly', 'facility_code, month'),
    ):
        connection.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})'))
