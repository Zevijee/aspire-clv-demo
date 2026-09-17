"""Baseline schema upgrade. Explicitly invoked by the migration command only."""
from sqlalchemy import text
from data.models import facilities, admissions, discharges, stays, payer_changes, hospital_reporting, admissions_reporting

def prepare_stays(connection):
    stays.metadata.create_all(connection)
    connection.execute(text("""
        ALTER TABLE adt_resident_stays
        ADD COLUMN IF NOT EXISTS initial_payer_type varchar(40),
        ADD COLUMN IF NOT EXISTS initial_payer_name varchar(120)
    """))
    connection.execute(
        text("""
        INSERT INTO adt_census_state (id, ready) VALUES (1, false) ON CONFLICT DO NOTHING
    """)
    )
    connection.execute(
        text("""
        CREATE OR REPLACE FUNCTION invalidate_adt_census() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          UPDATE adt_census_state SET ready = false WHERE id = 1;
          RETURN NULL;
        END $$
    """)
    )
    for table in (
        "facilities",
        "adt_admissions",
        "adt_discharges",
        "adt_resident_stays",
        "adt_census_daily",
    ):
        connection.execute(text(f"DROP TRIGGER IF EXISTS invalidate_adt_census ON {table}"))
        connection.execute(
            text(f"""
            CREATE TRIGGER invalidate_adt_census AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_adt_census()
        """)
        )

def prepare_payer_periods(connection):
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS adt_payer_periods (
            period_id varchar(36) PRIMARY KEY,
            stay_id varchar(36) NOT NULL,
            facility_code varchar(12) NOT NULL REFERENCES facilities(facility_code),
            start_date date NOT NULL, end_date date,
            payer_type varchar(40) NOT NULL, payer_name varchar(120) NOT NULL,
            CHECK (end_date IS NULL OR end_date >= start_date)
        )
    """))
    connection.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_payer_periods_stay ON adt_payer_periods(stay_id, start_date)
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS adt_payer_census_state (
            id integer PRIMARY KEY, ready boolean NOT NULL DEFAULT false,
            version varchar(80), start_date date, end_date date
        )
    """))
    connection.execute(text("""
        INSERT INTO adt_payer_census_state(id, ready) VALUES (1, false) ON CONFLICT DO NOTHING
    """))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION invalidate_payer_census() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            UPDATE adt_payer_census_state SET ready = false WHERE id = 1;
            RETURN NULL;
        END $$
    """))
    for name in ('adt_resident_stays', 'adt_payer_periods', 'adt_payer_changes',
                 'adt_admissions', 'adt_discharges', 'facilities'):
        connection.execute(text(f'DROP TRIGGER IF EXISTS invalidate_payer_census ON {name}'))
        connection.execute(text(f"""
            CREATE TRIGGER invalidate_payer_census AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {name} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_payer_census()
        """))

def prepare_admission_reporting(connection):
    admissions_reporting.metadata.create_all(connection)
    connection.execute(
        text("""
        INSERT INTO adt_reporting_state (id, revision, ready, admission_count)
        VALUES (1, 0, false, 0) ON CONFLICT (id) DO NOTHING
    """)
    )
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS adt_admissions_date_id
        ON adt_admissions (admission_date, admission_id)
    """)
    )
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS adt_admissions_facility_date
        ON adt_admissions (facility_code, admission_date)
    """)
    )
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS adt_admissions_payer_date
        ON adt_admissions (payer_type, admission_date)
    """)
    )
    connection.execute(
        text("""
        CREATE OR REPLACE FUNCTION invalidate_adt_reporting() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          UPDATE adt_reporting_state SET ready = false, revision = revision + 1 WHERE id = 1;
          RETURN NULL;
        END $$
    """)
    )
    for table in ("adt_admissions", "facilities"):
        # Fixed internal identifiers only; no user input is interpolated into DDL.
        connection.execute(text(f"DROP TRIGGER IF EXISTS invalidate_adt_reporting ON {table}"))
        connection.execute(
            text(f"""
            CREATE TRIGGER invalidate_adt_reporting
            AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION invalidate_adt_reporting()
        """)
        )

def upgrade(connection):
    for model in (facilities, admissions, discharges, stays, payer_changes, hospital_reporting, admissions_reporting):
        model.metadata.create_all(connection)
    connection.execute(text("ALTER TABLE facilities ADD COLUMN IF NOT EXISTS portfolio VARCHAR(80)"))
    connection.execute(text("ALTER TABLE facilities ALTER COLUMN portfolio SET NOT NULL"))
    connection.execute(text("ALTER TABLE adt_admissions ADD COLUMN IF NOT EXISTS is_readmission BOOLEAN NOT NULL DEFAULT FALSE"))
    connection.execute(text("ALTER TABLE adt_admissions ADD COLUMN IF NOT EXISTS readmission_days_since_prior INTEGER"))
    prepare_stays(connection)
    prepare_payer_periods(connection)
    prepare_admission_reporting(connection)
