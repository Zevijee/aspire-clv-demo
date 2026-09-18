-- manage.py applies this once, before generators, and records it in sandbox_schema_migrations.
-- New databases already create states with only its state primary key.
-- Transaction boundaries are owned by BaseGenerator.migrate().

ALTER TABLE IF EXISTS states
    DROP COLUMN IF EXISTS portfolio_count,
    DROP COLUMN IF EXISTS region_count,
    DROP COLUMN IF EXISTS facility_count,
    DROP COLUMN IF EXISTS total_beds;
