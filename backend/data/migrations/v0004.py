"""Shared source identities, scoped seed state and reporting coverage.

Schema only. This does not assign an organization, import source data, mark a
database as demo, regenerate records or start a reporting refresh.
"""
from sqlalchemy import text

from data.models import canonical, reporting_publication, seed_operations
from data.migrations.report_invalidation import replace_invalidation_triggers


def upgrade(connection):
    canonical.organizations.create(connection, checkfirst=True)
    connection.execute(text("ALTER TABLE facilities ADD COLUMN IF NOT EXISTS organization_id varchar(64)"))
    connection.execute(text("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_facilities_organization_code'
            AND conrelid='facilities'::regclass) THEN
            ALTER TABLE facilities ADD CONSTRAINT uq_facilities_organization_code
            UNIQUE (organization_id, facility_code);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_facilities_organization'
            AND conrelid='facilities'::regclass) THEN
            ALTER TABLE facilities ADD CONSTRAINT fk_facilities_organization
            FOREIGN KEY (organization_id) REFERENCES organizations(organization_id);
        END IF;
    END $$"""))
    canonical.metadata.create_all(connection)
    seed_operations.metadata.create_all(connection)
    reporting_publication.metadata.create_all(connection)
    # Carry forward only coverage supported by already-published legacy data.
    # This is a metadata backfill, not source generation or an aggregate refresh.
    connection.execute(text("""
        INSERT INTO reporting_dataset_coverage(dataset,facility_code,date,rules_version)
        SELECT 'daily_activity',f.facility_code,d.day::date,'legacy-published-v3'
        FROM adt_reporting_state s CROSS JOIN facilities f
        CROSS JOIN LATERAL generate_series(s.first_date::timestamp,s.latest_date::timestamp,interval '1 day') d(day)
        WHERE s.id=1 AND s.ready
        ON CONFLICT DO NOTHING
    """))
    for dataset, state_table in (('daily_census', 'adt_census_state'), ('payer_census', 'adt_payer_census_state')):
        connection.execute(text(f"""
            INSERT INTO reporting_dataset_coverage(dataset,facility_code,date,rules_version)
            SELECT :dataset,c.facility_code,c.census_date,'legacy-published-v3'
            FROM adt_census_daily c JOIN {state_table} s ON s.id=1 AND s.ready
                AND c.census_date BETWEEN s.start_date AND s.end_date
            ON CONFLICT DO NOTHING
        """), {'dataset': dataset})
    connection.execute(text("""
        INSERT INTO reporting_dataset_coverage(dataset,facility_code,date,rules_version)
        SELECT 'monthly_activity',c.facility_code,c.census_date,'legacy-published-v3'
        FROM adt_census_daily c JOIN adt_activity_monthly m ON m.facility_code=c.facility_code
            AND m.month=date_trunc('month',c.census_date)::date
        JOIN adt_census_state s ON s.id=1 AND s.ready AND c.census_date BETWEEN s.start_date AND s.end_date
        ON CONFLICT DO NOTHING
    """))
    connection.execute(text("""
        INSERT INTO reporting_dataset_coverage(dataset,facility_code,date,rules_version)
        SELECT 'referring_hospitals',f.facility_code,d.day::date,'legacy-published-v3'
        FROM adt_referring_hospital_publication p CROSS JOIN facilities f
        CROSS JOIN LATERAL generate_series(p.start_date::timestamp,p.end_date::timestamp,interval '1 day') d(day)
        WHERE p.id=1 ON CONFLICT DO NOTHING
    """))
    replace_invalidation_triggers(connection)
