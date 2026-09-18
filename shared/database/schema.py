"""Single relational schema imported by the seeder and future API.

Use manage.py stage and edit staged/schema.py while the API is running.
The sandbox publishes the reviewed schema and migrations when update is requested.
Table/column info holds documentation without changing database DDL.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, MetaData, PrimaryKeyConstraint, String, Table, UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
migration_history = Table('sandbox_schema_migrations', metadata,
    Column('name', String, primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('applied_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
run_history = Table('sandbox_generator_runs', metadata,
    Column('name', String, primary_key=True),
    Column('row_counts', JSON, nullable=False),
    Column('completed_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)

states = Table('states', metadata,
    Column('state', String(2), primary_key=True),
)
portfolios = Table('portfolios', metadata,
    Column('portfolio_id', Uuid, primary_key=True),
    Column('state', String(2), ForeignKey('states.state'), nullable=False),
    Column('portfolio', String, nullable=False),
    Column('region_count', Integer, nullable=False),
    Column('facility_count', Integer, nullable=False),
    Column('total_beds', Integer, nullable=False),
    UniqueConstraint('state', 'portfolio'),
    CheckConstraint('region_count >= 0 AND facility_count >= 0 AND total_beds >= 0'),
)
regions = Table('regions', metadata,
    Column('region_id', Uuid, primary_key=True),
    Column('portfolio_id', Uuid, ForeignKey('portfolios.portfolio_id'), nullable=False),
    Column('region', String, nullable=False),
    Column('facility_count', Integer, nullable=False),
    Column('total_beds', Integer, nullable=False),
    UniqueConstraint('portfolio_id', 'region'),
    CheckConstraint('facility_count >= 0 AND total_beds >= 0'),
)
facilities = Table('facilities', metadata,
    Column('facility_id', Uuid, primary_key=True),
    Column('region_id', Uuid, ForeignKey('regions.region_id'), nullable=False),
    Column('facility', String, nullable=False),
    Column('beds', Integer, nullable=False),
    UniqueConstraint('region_id', 'facility'),
    CheckConstraint('beds >= 0'),
)
residents = Table('residents', metadata,
    Column('resident_id', Uuid, primary_key=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False, index=True),
    Column('gender', String(6), nullable=False),
    Column('first_name', String, nullable=False),
    Column('last_name', String, nullable=False),
    CheckConstraint("gender IN ('male', 'female')"),
    UniqueConstraint('first_name', 'last_name', deferrable=True, initially='DEFERRED'),
)
payers = Table('payers', metadata,
    Column('payer_id', Uuid, primary_key=True),
    Column('payer_type', String, nullable=False, index=True),
    Column('payer_name', String, nullable=False),
    Column('is_skilled', Boolean, nullable=False),
    UniqueConstraint('payer_type', 'payer_name'),
)
res_stays = Table('res_stays', metadata,
    Column('stay_id', Uuid, primary_key=True),
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), nullable=False, index=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False, index=True),
    Column('admission_number', Integer, nullable=False),
    Column('admission_date', Date, nullable=False, index=True),
    Column('discharge_date', Date, index=True),
    UniqueConstraint('resident_id', 'admission_number'),
    CheckConstraint('admission_number BETWEEN 1 AND 7'),
    CheckConstraint('discharge_date IS NULL OR discharge_date > admission_date'),
)
res_payer_stays = Table('res_payer_stays', metadata,
    Column('payer_stay_id', Uuid, primary_key=True),
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('period_number', Integer, nullable=False),
    Column('start_date', Date, nullable=False, index=True),
    Column('end_date', Date, index=True),
    Column('start_reason', String, nullable=False),
    Column('end_reason', String),
    UniqueConstraint('stay_id', 'period_number'),
    CheckConstraint('period_number BETWEEN 1 AND 3'),
    CheckConstraint('end_date IS NULL OR end_date > start_date'),
    CheckConstraint("(period_number = 1 AND start_reason = 'admission') OR "
        "(period_number > 1 AND start_reason = 'payer_change')"),
    CheckConstraint("(end_date IS NULL AND end_reason IS NULL) OR "
        "(end_date IS NOT NULL AND end_reason IS NOT NULL "
        "AND end_reason IN ('payer_change', 'discharge'))"),
)

admission_logs = Table('admission_logs', metadata,
    # One admission log per saved admission episode.
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('admission_date', Date, nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('source_type', String, nullable=False),
    Column('source_name', String, nullable=False),
    Column('is_readmission', Boolean, nullable=False),
    Column('is_30_day_readmission', Boolean, nullable=False),
    CheckConstraint("source_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community')"),
    CheckConstraint("length(trim(source_name)) > 0"),
    CheckConstraint('NOT is_30_day_readmission OR is_readmission'),
)

medicaid_applications = Table('medicaid_applications', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('payer_stay_id', Uuid, ForeignKey('res_payer_stays.payer_stay_id'), nullable=False, unique=True),
    Column('application_date', Date, nullable=False, index=True),
    Column('approved_date', Date, index=True),
    Column('approved_payer_id', Uuid, ForeignKey('payers.payer_id')),
    CheckConstraint('(approved_date IS NULL AND approved_payer_id IS NULL) OR '
        '(approved_date IS NOT NULL AND approved_payer_id IS NOT NULL AND approved_date >= application_date)'),
)

discharge_logs = Table('discharge_logs', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('discharge_date', Date, nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('destination_type', String, nullable=False),
    Column('destination_name', String, nullable=False),
    Column('is_deceased', Boolean, nullable=False),
    Column('los', Integer, nullable=False),
    CheckConstraint("destination_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community', 'Funeral Home')"),
    CheckConstraint("length(trim(destination_name)) > 0"),
    CheckConstraint("is_deceased = (destination_type = 'Funeral Home')"),
    CheckConstraint('los > 0'),
)

daily_admission_facts = Table('daily_admission_facts', metadata,
    # One row per (date, facility, payer, referral source) that had admissions.
    # Parent location totals are GROUP BY results, never stored copies, so a
    # scope is never double counted with its own children. Days and facilities
    # with no admissions have no rows; absence means zero, not missing.
    Column('summary_date', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('source_type', String, nullable=False),
    Column('source_name', String, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('readmissions', Integer, nullable=False),
    Column('readmissions_30_day', Integer, nullable=False),
    Column('medicaid_pending_admissions', Integer, nullable=False),
    PrimaryKeyConstraint('summary_date', 'facility_id', 'payer_id', 'source_type', 'source_name'),
    CheckConstraint("source_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community')"),
    CheckConstraint("length(trim(source_name)) > 0"),
    CheckConstraint('admissions > 0'),
    CheckConstraint('readmissions BETWEEN 0 AND admissions'),
    CheckConstraint('readmissions_30_day BETWEEN 0 AND readmissions'),
    CheckConstraint('medicaid_pending_admissions BETWEEN 0 AND admissions'),
    Index('ix_daily_admission_facts_facility', 'facility_id', 'summary_date'),
)

daily_runs = Table('sandbox_daily_runs', metadata,
    Column('generator', String, primary_key=True),
    Column('simulation_date', Date, primary_key=True),
    Column('row_counts', JSON, nullable=False),
    Column('completed_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
adt_resident_state = Table('sandbox_adt_residents', metadata,
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), primary_key=True),
    Column('admission_limit', Integer, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('last_discharge', Date),
    Column('eligible_after', Date),
    Column('is_deceased', Boolean, nullable=False),
    Column('skilled_used', Integer, nullable=False),
    CheckConstraint('admission_limit BETWEEN 1 AND 7 AND admissions BETWEEN 1 AND admission_limit'),
    CheckConstraint('skilled_used BETWEEN 0 AND 100'),
)
adt_active_stays = Table('sandbox_adt_active_stays', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    # Future intentions are kept here, never as completed clinical events.
    Column('planned_discharge', Date, nullable=False),
    Column('payer_plan', JSONB, nullable=False),
    Column('skilled_days', Integer, nullable=False),
    Column('medicaid_approval', JSONB),
)
adt_daily_census = Table('adt_daily_census', metadata,
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), primary_key=True),
    Column('census_date', Date, primary_key=True),
    Column('beds', Integer, nullable=False),
    Column('opening_census', Integer, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('discharges', Integer, nullable=False),
    Column('closing_census', Integer, nullable=False),
    CheckConstraint('closing_census = opening_census + admissions - discharges'),
    CheckConstraint('beds >= 0 AND opening_census >= 0 AND admissions >= 0 AND discharges >= 0'),
    CheckConstraint('closing_census BETWEEN 0 AND beds'),
)


migration_checksums = Table('database_migration_checksums', metadata,
    Column('revision', String(64), primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('applied_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
backfill_runs = Table('database_backfill_runs', metadata,
    Column('name', String, primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('status', String, nullable=False),
    Column('checkpoint', JSONB, nullable=False),
    Column('processed', Integer, nullable=False, server_default='0'),
    Column('changed', Integer, nullable=False, server_default='0'),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('pending', 'running', 'deferred', 'complete')"),
    CheckConstraint('processed >= 0 AND changed >= 0'),
)

# Documentation stays beside the schema. `info` does not change database DDL.
_descriptions = {
    'states': 'Top-level state codes; counts are derived from child records.',
    'portfolios': 'Portfolios within states. Stored reference counts describe the source facility catalog.',
    'regions': 'Regions within portfolios; facility groups used by hospital referral weighting.',
    'facilities': 'Facilities and their licensed/demo bed capacity.',
    'residents': 'Saved resident identities associated with a facility. Stays reference these saved IDs.',
    'payers': 'Payer catalog. Skilled classification applies to Medicare categories and VA.',
    'res_stays': 'Admission-to-discharge episodes. A null discharge date means currently admitted.',
    'res_payer_stays': 'Payer periods inside an admission episode. The active period has no end date.',
    'admission_logs': 'One actual admission event per episode, including referring source and readmission flags.',
    'medicaid_applications': 'Admissions that started pending Medicaid. Preserves application/approval metrics after payer records are retroactively corrected.',
    'discharge_logs': 'One actual discharge event per closed episode. LOS measures the final payer period.',
    'daily_admission_facts': 'Additive daily admission measures at facility/payer/source grain. Reports group these rows; parent scopes are not stored.',
    'adt_daily_census': 'Daily facility census: opening + admissions - discharges = closing.',
    'sandbox_schema_migrations': 'Preserved legacy SQL migration history; new migrations use Alembic.',
    'sandbox_generator_runs': 'Reference-generator completion records used to retain existing data.',
    'sandbox_daily_runs': 'Committed generator/day checkpoints; independent of schema and backfill versions.',
    'sandbox_adt_residents': 'Internal simulation state for readmissions, eligibility and cumulative skilled days.',
    'sandbox_adt_active_stays': 'Internal future simulation plans. These are not completed clinical events.',
    'database_migration_checksums': 'Checksums of applied Alembic revisions and their frozen artifacts.',
    'database_backfill_runs': 'Immutable job identity, durable batch checkpoint and cumulative progress per database.',
}
for _name, _description in _descriptions.items():
    metadata.tables[_name].info['description'] = _description

discharge_logs.c.los.info['description'] = 'Discharge date minus the final payer period start date, in days; not admission LOS.'
admission_logs.c.is_readmission.info['description'] = 'Resident has a previous admission episode.'
admission_logs.c.is_30_day_readmission.info['description'] = 'Return within 30 days of the previous discharge; also a readmission.'
daily_admission_facts.c.source_name.info['description'] = 'Referring source name; referring-hospital metrics count distinct names where source_type is Hospital.'
daily_admission_facts.c.medicaid_pending_admissions.info['description'] = 'Admissions that began pending Medicaid; retained after retroactive payer approval.'
res_payer_stays.c.end_date.info['description'] = 'Exclusive period end; null until payer change or discharge actually occurs.'
medicaid_applications.c.application_date.info['description'] = 'Admission date when Medicaid coverage was pending; a row permanently identifies a pending-at-admission case.'
medicaid_applications.c.approved_date.info['description'] = 'Actual approval date; null while unresolved. Approved coverage is retroactive to application_date.'
adt_active_stays.c.medicaid_approval.info['description'] = 'Private planned approval date and payer ID; not a completed approval event.'
backfill_runs.c.checkpoint.info['description'] = 'Job-owned JSON cursor/watermark committed atomically with each batch.'
