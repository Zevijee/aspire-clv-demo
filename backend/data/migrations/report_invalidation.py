"""Replace coarse legacy invalidation with field-aware serving-data triggers.

Only versioned migrations call this helper. It executes no DDL on import and is
not used by API requests, reporting refreshes, or source generators.
"""
from sqlalchemy import text


# These identifiers are fixed schema-owned values, never request input.
_CENSUS = {
    "facilities": (),
    "adt_admissions": ("admission_date", "facility_code"),
    "adt_discharges": ("start_date", "discharge_date", "facility_code"),
    "adt_resident_stays": ("start_date", "end_date", "facility_code"),
    "adt_census_daily": ("facility_code", "census_date", "opening_census", "closing_census", "admissions", "discharges"),
}
_PAYER = {
    "facilities": (),
    "adt_admissions": ("admission_date", "facility_code", "payer_type"),
    "adt_discharges": ("start_date", "discharge_date", "facility_code", "payer_type"),
    "adt_resident_stays": ("start_date", "end_date", "facility_code", "initial_payer_type"),
    "adt_payer_periods": ("stay_id", "facility_code", "start_date", "end_date", "payer_type"),
    "adt_payer_changes": ("facility_code", "effective_date", "previous_payer_start_date", "new_payer_end_date",
                          "previous_payer_type", "new_payer_type", "change_category"),
}
_ADMISSIONS = {
    "facilities": (),
    "adt_admissions": ("admission_date", "facility_code", "payer_type", "admission_source_type",
                       "admission_source_name", "is_readmission", "readmission_days_since_prior"),
}
_CACHE_TABLES = (
    "facilities", "adt_admissions", "adt_discharges", "adt_resident_stays",
    "adt_payer_periods", "adt_payer_changes", "adt_census_daily", "census_bed_holds_daily",
    "adt_admissions_daily", "adt_admissions_sources_daily", "adt_activity_monthly",
    "adt_referring_hospitals", "adt_referring_hospital_monthly", "adt_referring_hospital_publication",
)


def _replace_family(connection, declarations, original_trigger, function):
    for table, columns in declarations.items():
        structural = original_trigger + "_structure"
        update = original_trigger + "_fields"
        for trigger in (original_trigger, structural, update):
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        connection.execute(text(f"""
            CREATE TRIGGER {structural} AFTER INSERT OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION {function}()
        """))
        if columns:
            connection.execute(text(f"""
                CREATE TRIGGER {update} AFTER UPDATE OF {', '.join(columns)} ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION {function}()
            """))


def replace_invalidation_triggers(connection):
    """Preserve known-good counts on label edits; all changed displays lose cache.

    INSERT/DELETE/TRUNCATE still invalidate completeness. UPDATE OF is deliberately
    conservative when a writer explicitly submits a metric column, even if its
    value is unchanged. Reference writers should submit only their owned fields.
    """
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION invalidate_adt_census() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            UPDATE adt_census_state SET ready=false WHERE id=1;
            RETURN NULL;
        END $$
    """))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION invalidate_payer_census() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            UPDATE adt_payer_census_state SET ready=false WHERE id=1;
            RETURN NULL;
        END $$
    """))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION invalidate_adt_reporting() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            UPDATE adt_reporting_state SET ready=false WHERE id=1;
            RETURN NULL;
        END $$
    """))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION invalidate_adt_report_cache() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            UPDATE adt_reporting_state SET revision=revision+1 WHERE id=1;
            RETURN NULL;
        END $$
    """))
    _replace_family(connection, _CENSUS, "invalidate_adt_census", "invalidate_adt_census")
    _replace_family(connection, _PAYER, "invalidate_payer_census", "invalidate_payer_census")
    _replace_family(connection, _ADMISSIONS, "invalidate_adt_reporting", "invalidate_adt_reporting")
    for table in _CACHE_TABLES:
        connection.execute(text(f"DROP TRIGGER IF EXISTS invalidate_adt_report_cache ON {table}"))
        connection.execute(text(f"""
            CREATE TRIGGER invalidate_adt_report_cache
            AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION invalidate_adt_report_cache()
        """))
